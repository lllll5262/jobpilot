"""简历检索增强生成链路测试。"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import AppException
from app.main import app
from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_rag_service import ResumeRagService


def make_match(*, parent_id: str, chunk_id: str, score: float) -> ResumeChunkMatch:
    """构造属于同一份简历的向量命中。"""
    return ResumeChunkMatch(
        resume_id=10,
        doc_hash="a" * 64,
        parent_id=parent_id,
        chunk_id=chunk_id,
        text=f"子块 {chunk_id}",
        parent_content=f"父块 {parent_id}：使用 Redis 和 Lua 实现库存扣减。",
        score=score,
    )


class FakeResumeService:
    """记录 RAG Service 的简历读取和检索参数。"""

    def __init__(self, matches: list[ResumeChunkMatch]) -> None:
        self.matches = matches
        self.search_values: dict[str, Any] | None = None

    async def get(self, *, user_id: int, resume_id: int | None) -> Any:
        assert user_id == 1
        return SimpleNamespace(id=resume_id or 10)

    async def search_context(self, **values: Any) -> list[ResumeChunkMatch]:
        self.search_values = values
        return self.matches


class FakeLLM:
    """返回固定 JSON，并保留实际注入模型的上下文。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))
        return self.result


def test_resume_rag_route_is_registered() -> None:
    """OpenAPI 应暴露完整的简历问答生成入口。"""
    assert "/users/{user_id}/resumes/answer" in app.openapi()["paths"]


def test_resume_rag_retrieves_deduplicates_and_generates_grounded_answer() -> None:
    """同一父块的多个子块只能向生成模型注入一次。"""

    async def run() -> None:
        resume_service = FakeResumeService(
            [
                make_match(parent_id="p1", chunk_id="c1", score=0.9),
                make_match(parent_id="p1", chunk_id="c2", score=0.8),
                make_match(parent_id="p2", chunk_id="c3", score=0.7),
            ]
        )
        llm = FakeLLM(
            {
                "answer": "候选人使用 Redis 和 Lua 实现了库存扣减。",
                "cited_parent_ids": ["p1", "p1"],
            }
        )
        service = ResumeRagService(
            llm_client=llm,
            resume_service=resume_service,  # type: ignore[arg-type]
        )

        result = await service.answer(
            user_id=1,
            resume_id=None,
            query="候选人是否使用过 Redis？",
            limit=8,
        )

        assert resume_service.search_values is not None
        assert resume_service.search_values["resume_id"] == 10
        assert [context.parent_id for context in result.contexts] == ["p1", "p2"]
        assert result.cited_parent_ids == ["p1"]
        assert len(llm.calls) == 1
        system_prompt, user_prompt = llm.calls[0]
        assert "只能依据" in system_prompt
        prompt_payload = json.loads(user_prompt)
        assert prompt_payload["question"] == "候选人是否使用过 Redis？"
        assert [item["parent_id"] for item in prompt_payload["resume_contexts"]] == [
            "p1",
            "p2",
        ]

    asyncio.run(run())


def test_resume_rag_returns_deterministic_answer_when_retrieval_is_empty() -> None:
    """没有上下文时不调用模型，避免无依据生成。"""

    async def run() -> None:
        llm = FakeLLM({})
        service = ResumeRagService(
            llm_client=llm,
            resume_service=FakeResumeService([]),  # type: ignore[arg-type]
        )

        result = await service.answer(
            user_id=1,
            resume_id=10,
            query="不存在的信息",
            limit=8,
        )

        assert result.answer == ResumeRagService.INSUFFICIENT_CONTEXT_ANSWER
        assert result.contexts == []
        assert result.cited_parent_ids == []
        assert llm.calls == []

    asyncio.run(run())


def test_resume_rag_rejects_citations_outside_retrieved_context() -> None:
    """模型不能引用本次检索结果之外的父块。"""

    async def run() -> None:
        service = ResumeRagService(
            llm_client=FakeLLM(
                {
                    "answer": "候选人使用过 Redis。",
                    "cited_parent_ids": ["unknown-parent"],
                }
            ),
            resume_service=FakeResumeService(  # type: ignore[arg-type]
                [make_match(parent_id="p1", chunk_id="c1", score=0.9)]
            ),
        )

        with pytest.raises(AppException, match="invalid resume citations"):
            await service.answer(
                user_id=1,
                resume_id=10,
                query="候选人是否使用过 Redis？",
                limit=8,
            )

    asyncio.run(run())
