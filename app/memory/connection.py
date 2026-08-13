"""Redis asyncio 客户端生命周期。"""

from collections.abc import AsyncIterator

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()

# Session/Memory 使用 JSON 字符串，开启 decode_responses 可简化边界处理。
redis_client: Redis = Redis.from_url(
    settings.redis_url.get_secret_value(),
    decode_responses=True,
    health_check_interval=30,
)


async def get_redis_client() -> AsyncIterator[Redis]:
    """向 FastAPI 依赖提供共享连接池客户端。"""
    yield redis_client


async def dispose_redis() -> None:
    """应用停止时显式关闭 redis-py 异步连接池。"""
    await redis_client.aclose()
