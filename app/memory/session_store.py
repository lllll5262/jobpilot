"""Redis Session 元数据与短期分析 Cache。"""

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.core.exceptions import AppException
from app.memory.keys import analysis_cache_key, session_key, session_turn_key


class SessionStore:
    """保存会话归属、活跃时间和单调递增轮次。"""

    def __init__(self, client: Redis, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def ensure_session(self, *, session_id: str, user_id: int) -> None:
        """创建或校验会话，禁止不同用户复用同一个 session_id。"""
        key = session_key(session_id)
        created = await self._client.hsetnx(key, "user_id", str(user_id))
        owner = await self._client.hget(key, "user_id")
        if owner != str(user_id):
            raise AppException(
                "Session does not belong to current user", code=40307, status_code=403
            )

        now = datetime.now(UTC).isoformat()
        async with self._client.pipeline(transaction=True) as pipe:
            if created:
                pipe.hset(key, mapping={"created_at": now})
            pipe.hset(key, mapping={"updated_at": now})
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def require_session(self, *, session_id: str, user_id: int) -> None:
        """只读校验会话存在且属于当前用户。"""
        owner = await self._client.hget(session_key(session_id), "user_id")
        if owner is None:
            raise AppException("Session not found", code=40407, status_code=404)
        if owner != str(user_id):
            raise AppException(
                "Session does not belong to current user", code=40307, status_code=403
            )

    async def next_turn(self, session_id: str) -> int:
        """原子递增会话轮次，并刷新 Session TTL。"""
        turn_key = session_turn_key(session_id)
        turn = await self._client.incr(turn_key)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.expire(turn_key, self._ttl_seconds)
            pipe.expire(session_key(session_id), self._ttl_seconds)
            await pipe.execute()
        return int(turn)


class AnalysisContextCache:
    """缓存最近岗位分析摘要，辅助“刚才那个”之类的追问。"""

    def __init__(
        self,
        client: Redis,
        *,
        ttl_seconds: int,
        max_items: int = 5,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._max_items = max_items

    async def list_recent(self, session_id: str) -> list[dict[str, Any]]:
        """读取最近分析上下文；缓存损坏时安全返回空列表。"""
        payload = await self._client.get(analysis_cache_key(session_id))
        if payload is None:
            return []
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    async def append(self, session_id: str, item: dict[str, Any]) -> None:
        """追加一个分析摘要，并只保留最近固定数量。"""
        items = await self.list_recent(session_id)
        items.append(item)
        await self._client.set(
            analysis_cache_key(session_id),
            json.dumps(items[-self._max_items :], ensure_ascii=False),
            ex=self._ttl_seconds,
        )
