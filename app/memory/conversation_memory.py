"""Redis 最近 N 轮 Conversation History。"""

from datetime import UTC, datetime

from redis.asyncio import Redis

from app.memory.keys import conversation_key
from app.schemas.agent import ConversationMessage


class ConversationMemory:
    """使用 Redis List 保存受长度约束的短期对话。"""

    def __init__(self, client: Redis, *, max_turns: int, ttl_seconds: int) -> None:
        self._client = client
        self._max_messages = max_turns * 2
        self._ttl_seconds = ttl_seconds

    async def get_recent(self, session_id: str) -> list[ConversationMessage]:
        """按时间正序读取最近 N 轮消息。"""
        values = await self._client.lrange(conversation_key(session_id), 0, -1)
        messages: list[ConversationMessage] = []
        for value in values:
            try:
                messages.append(ConversationMessage.model_validate_json(value))
            except ValueError:
                # 单条异常数据不应破坏整个会话。
                continue
        return messages

    async def append_turn(self, session_id: str, *, user: str, assistant: str) -> None:
        """原子追加一轮消息、裁剪长度并刷新 TTL。"""
        now = datetime.now(UTC)
        values = [
            ConversationMessage(role="user", content=user, created_at=now),
            ConversationMessage(role="assistant", content=assistant, created_at=now),
        ]
        key = conversation_key(session_id)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, *(item.model_dump_json() for item in values))
            pipe.ltrim(key, -self._max_messages, -1)
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()
