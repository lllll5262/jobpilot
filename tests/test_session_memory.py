"""阶段 7 Redis Session、Memory、Cache 与 Checkpointer 测试。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.core.exceptions import AppException
from app.main import app
from app.memory.checkpointer import RedisCheckpointSaver
from app.memory.conversation_memory import ConversationMemory
from app.memory.keys import (
    analysis_cache_key,
    checkpoint_index_key,
    conversation_key,
    session_key,
)
from app.memory.session_store import AnalysisContextCache, SessionStore
from app.schemas.agent import JobAgentSessionRequest, JobAgentSessionResponse
from app.schemas.persistence import AnalysisRecord, JobRecord
from app.services.session_service import SessionService

CREATED_AT = datetime(2026, 8, 12, tzinfo=UTC)

JOB_DATA = {
    "job_title": "Java后端工程师",
    "required_skills": ["Java"],
    "preferred_skills": [],
    "education": None,
    "experience": None,
}
MATCH_DATA = {
    "match_score": 88,
    "matched_skills": ["Java"],
    "missing_skills": [],
    "strong_points": ["Java 能力匹配"],
    "weak_points": [],
    "recommendation": "RECOMMEND",
}


class FakePipeline:
    """支持本阶段所需 Redis Pipeline 命令的内存替身。"""

    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def __getattr__(self, name: str):
        def enqueue(*args: Any, **kwargs: Any) -> FakePipeline:
            self._commands.append((name, args, kwargs))
            return self

        return enqueue

    async def execute(self) -> list[Any]:
        results = []
        for name, args, kwargs in self._commands:
            results.append(await getattr(self._client, name)(*args, **kwargs))
        return results


class FakeRedis:
    """覆盖 Session/Memory/Checkpointer 使用的普通 Redis 命令。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: defaultdict[str, dict[str, str]] = defaultdict(dict)
        self.lists: defaultdict[str, list[str]] = defaultdict(list)
        self.sorted_sets: defaultdict[str, dict[str, float]] = defaultdict(dict)
        self.sets: defaultdict[str, set[str]] = defaultdict(set)

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        del transaction
        return FakePipeline(self)

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True

    async def set(self, key: str, value: str, **kwargs: Any) -> bool:
        del kwargs
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def hsetnx(self, key: str, field: str, value: str) -> bool:
        if field in self.hashes[key]:
            return False
        self.hashes[key][field] = value
        return True

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes[key].get(field)

    async def hset(
        self,
        key: str,
        *,
        mapping: dict[str, str],
    ) -> int:
        self.hashes[key].update(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes[key])

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def rpush(self, key: str, *values: str) -> int:
        self.lists[key].extend(values)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        values = self.lists[key]
        normalized_start = max(len(values) + start, 0) if start < 0 else start
        normalized_end = len(values) + end if end < 0 else end
        self.lists[key] = values[normalized_start : normalized_end + 1]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists[key]
        normalized_end = len(values) - 1 if end == -1 else end
        return values[start : normalized_end + 1]

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.sorted_sets[key].update(mapping)
        return len(mapping)

    async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        members = sorted(
            self.sorted_sets[key],
            key=self.sorted_sets[key].get,
            reverse=True,
        )
        normalized_end = len(members) - 1 if end == -1 else end
        return members[start : normalized_end + 1]

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        members = sorted(self.sorted_sets[key], key=self.sorted_sets[key].get)
        normalized_end = len(members) - 1 if end == -1 else end
        return members[start : normalized_end + 1]

    async def sadd(self, key: str, *values: str) -> int:
        self.sets[key].update(values)
        return len(values)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets[key])

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
            self.lists.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.sets.pop(key, None)
        return len(keys)


class StubSessionAgent:
    """记录 SessionService 传入的历史与分析上下文。"""

    def __init__(self) -> None:
        self.inputs: list[tuple[int, int, int]] = []

    async def chat(
        self,
        request: JobAgentSessionRequest,
        *,
        turn: int,
        history: list[Any],
        analysis_context: list[dict[str, Any]],
    ) -> JobAgentSessionResponse:
        self.inputs.append((turn, len(history), len(analysis_context)))
        if request.jd_text is None:
            return JobAgentSessionResponse(
                session_id=request.session_id,
                turn=turn,
                final_answer="和刚才的 Java 岗位相比，这次追问已读取历史上下文。",
                analysis=None,
                job=None,
                tool_trace=[],
                history_turns=len(history) // 2,
            )
        job = JobRecord(
            id=30,
            user_id=1,
            raw_text=request.jd_text,
            job=JOB_DATA,
            created_at=CREATED_AT,
        )
        analysis = AnalysisRecord(
            id=40,
            user_id=1,
            resume_id=10,
            profile_id=20,
            job_id=30,
            result=MATCH_DATA,
            created_at=CREATED_AT,
        )
        return JobAgentSessionResponse(
            session_id=request.session_id,
            turn=turn,
            final_answer="该岗位匹配分数为 88，建议投递。",
            analysis=analysis,
            job=job,
            tool_trace=[
                "get_candidate_profile",
                "parse_job_description",
                "calculate_job_match",
                "save_analysis",
            ],
            history_turns=len(history) // 2,
        )


def test_session_memory_keys_use_separate_namespaces() -> None:
    """Session、Memory、Cache 和 Checkpoint 必须使用不同 Key 空间。"""
    keys = {
        session_key("session-001"),
        conversation_key("session-001"),
        analysis_cache_key("session-001"),
        checkpoint_index_key("session-001", "turn:1"),
    }
    assert len(keys) == 4


def test_conversation_memory_keeps_recent_n_turns() -> None:
    """ConversationMemory 应裁剪旧消息，仅保留最近 N 轮。"""

    async def run() -> None:
        client = FakeRedis()
        memory = ConversationMemory(client, max_turns=2, ttl_seconds=3600)  # type: ignore[arg-type]
        await memory.append_turn("session-001", user="问题1", assistant="回答1")
        await memory.append_turn("session-001", user="问题2", assistant="回答2")
        await memory.append_turn("session-001", user="问题3", assistant="回答3")
        messages = await memory.get_recent("session-001")
        assert [message.content for message in messages] == ["问题2", "回答2", "问题3", "回答3"]

    asyncio.run(run())


def test_redis_checkpointer_round_trip() -> None:
    """轻量 Checkpointer 应保存并恢复 LangGraph Checkpoint 与 Pending Writes。"""

    async def run() -> None:
        client = FakeRedis()
        saver = RedisCheckpointSaver(client, ttl_seconds=3600)  # type: ignore[arg-type]
        config = {"configurable": {"thread_id": "session-001", "checkpoint_ns": "turn:1"}}
        checkpoint = empty_checkpoint()
        saved_config = await saver.aput(
            config,
            checkpoint,
            {"source": "input", "step": -1, "parents": {}},
            {},
        )
        await saver.aput_writes(saved_config, [("messages", {"role": "user"})], "task-1")
        loaded = await saver.aget_tuple(config)
        assert loaded is not None
        assert loaded.checkpoint["id"] == checkpoint["id"]
        assert loaded.pending_writes == [("task-1", "messages", {"role": "user"})]

    asyncio.run(run())


def test_redis_checkpointer_runs_with_langgraph() -> None:
    """自定义 Checkpointer 应能被真实 StateGraph 异步执行链调用。"""

    class CounterState(TypedDict):
        value: int

    async def run() -> None:
        client = FakeRedis()
        saver = RedisCheckpointSaver(client, ttl_seconds=3600)  # type: ignore[arg-type]
        builder = StateGraph(CounterState)
        builder.add_node("increment", lambda state: {"value": state["value"] + 1})
        builder.add_edge(START, "increment")
        builder.add_edge("increment", END)
        graph = builder.compile(checkpointer=saver)
        result = await graph.ainvoke(
            {"value": 1},
            config={
                "configurable": {
                    "thread_id": "session-001:turn:1",
                }
            },
        )
        assert result == {"value": 2}
        latest = await saver.aget_tuple(
            {
                "configurable": {
                    "thread_id": "session-001:turn:1",
                }
            }
        )
        assert latest is not None
        assert latest.checkpoint["channel_values"]["value"] == 2

    asyncio.run(run())


def test_session_service_supplies_previous_turn_context() -> None:
    """第二轮追问应收到上一轮对话和岗位分析缓存。"""

    async def run() -> None:
        client = FakeRedis()
        agent = StubSessionAgent()
        service = SessionService(
            session_store=SessionStore(client, ttl_seconds=3600),  # type: ignore[arg-type]
            conversation_memory=ConversationMemory(
                client,
                max_turns=5,
                ttl_seconds=3600,  # type: ignore[arg-type]
            ),
            analysis_cache=AnalysisContextCache(client, ttl_seconds=3600),  # type: ignore[arg-type]
        )
        first = await service.chat(
            user_id=1,
            request=JobAgentSessionRequest(
                session_id="session-001",
                message="这个岗位怎么样？",
                jd_text="Java后端工程师，要求掌握 Java。",
            ),
            agent=agent,  # type: ignore[arg-type]
        )
        second = await service.chat(
            user_id=1,
            request=JobAgentSessionRequest(
                session_id="session-001",
                message="那和刚才那个比呢？",
            ),
            agent=agent,  # type: ignore[arg-type]
        )
        assert first.turn == 1
        assert second.turn == 2
        assert agent.inputs == [(1, 0, 0), (2, 2, 1)]
        assert second.history_turns == 2
        assert "刚才的 Java 岗位" in second.final_answer
        state = await service.get_state(user_id=1, session_id="session-001")
        assert len(state.messages) == 4
        assert len(state.recent_analyses) == 1

        with pytest.raises(AppException):
            await SessionStore(client, ttl_seconds=3600).ensure_session(
                session_id="session-001",
                user_id=2,
            )

    asyncio.run(run())


def test_session_agent_route_is_registered() -> None:
    """OpenAPI 应暴露带 session_id 的多轮会话接口。"""
    assert "/users/{user_id}/agents/job/chat" in app.openapi()["paths"]
    assert "/users/{user_id}/agents/job/sessions/{session_id}" in app.openapi()["paths"]
