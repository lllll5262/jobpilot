"""无需 RedisJSON/RediSearch 的轻量 LangGraph Redis Checkpointer。"""

import base64
import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from redis.asyncio import Redis

from app.memory.keys import (
    checkpoint_index_key,
    checkpoint_key,
    checkpoint_namespace_registry_key,
    checkpoint_scope,
    checkpoint_writes_key,
)


class RedisCheckpointSaver(BaseCheckpointSaver[str]):
    """基于普通 Redis 命令实现 LangGraph 异步 Checkpointer。"""

    def __init__(self, client: Redis, *, ttl_seconds: int) -> None:
        super().__init__()
        self._client = client
        self._ttl_seconds = ttl_seconds

    def _dump(self, value: Any) -> dict[str, str]:
        """用 LangGraph 官方 Serializer 编码，并转换为 JSON 可保存形式。"""
        type_name, payload = self.serde.dumps_typed(value)
        return {
            "type": type_name,
            "data": base64.b64encode(payload).decode("ascii"),
        }

    def _load(self, value: dict[str, str]) -> Any:
        """还原 LangGraph Serializer 产生的数据。"""
        return self.serde.loads_typed((value["type"], base64.b64decode(value["data"])))

    @staticmethod
    def _config_values(config: RunnableConfig) -> tuple[str, str, str | None]:
        """提取 LangGraph Checkpointer 约定的 configurable 字段。"""
        configurable = config.get("configurable", {})
        thread_id = str(configurable.get("thread_id", ""))
        if not thread_id:
            raise ValueError("thread_id is required for Redis checkpoint")
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = configurable.get("checkpoint_id")
        return thread_id, checkpoint_ns, str(checkpoint_id) if checkpoint_id else None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """保存一个 Checkpoint，并维护每个命名空间的时间索引。"""
        del new_versions
        thread_id, checkpoint_ns, parent_checkpoint_id = self._config_values(config)
        checkpoint_id = checkpoint["id"]
        data_key = checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
        index_key = checkpoint_index_key(thread_id, checkpoint_ns)
        registry_key = checkpoint_namespace_registry_key(thread_id)
        scope = checkpoint_scope(thread_id, checkpoint_ns)
        payload = json.dumps(
            {
                "checkpoint": self._dump(checkpoint),
                "metadata": self._dump(metadata),
                "parent_checkpoint_id": parent_checkpoint_id,
            },
            ensure_ascii=False,
        )
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.set(data_key, payload, ex=self._ttl_seconds)
            pipe.zadd(index_key, {checkpoint_id: time.time_ns()})
            pipe.expire(index_key, self._ttl_seconds)
            pipe.sadd(registry_key, scope)
            pipe.expire(registry_key, self._ttl_seconds)
            await pipe.execute()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """读取指定或最新的 Checkpoint，并恢复待处理写入。"""
        thread_id, checkpoint_ns, checkpoint_id = self._config_values(config)
        if checkpoint_id is None:
            latest = await self._client.zrevrange(
                checkpoint_index_key(thread_id, checkpoint_ns), 0, 0
            )
            if not latest:
                return None
            checkpoint_id = latest[0]

        payload = await self._client.get(checkpoint_key(thread_id, checkpoint_ns, checkpoint_id))
        if payload is None:
            return None
        record = json.loads(payload)
        pending_writes = await self._load_pending_writes(
            thread_id,
            checkpoint_ns,
            checkpoint_id,
        )
        result_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }
        parent_id = record.get("parent_checkpoint_id")
        parent_config: RunnableConfig | None = None
        if parent_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_id,
                }
            }
        return CheckpointTuple(
            config=result_config,
            checkpoint=self._load(record["checkpoint"]),
            metadata=self._load(record["metadata"]),
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """按最新优先列出一个线程命名空间中的 Checkpoint。"""
        if config is None:
            return
        thread_id, checkpoint_ns, _ = self._config_values(config)
        checkpoint_ids = await self._client.zrevrange(
            checkpoint_index_key(thread_id, checkpoint_ns),
            0,
            -1,
        )
        before_id = None
        if before is not None:
            _, _, before_id = self._config_values(before)
        yielded = 0
        for checkpoint_id in checkpoint_ids:
            if before_id is not None and checkpoint_id == before_id:
                continue
            item = await self.aget_tuple(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                }
            )
            if item is None:
                continue
            if filter and any(item.metadata.get(key) != value for key, value in filter.items()):
                continue
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                break

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """保存节点中间写入，使 LangGraph 可以恢复未完成任务。"""
        thread_id, checkpoint_ns, checkpoint_id = self._config_values(config)
        if checkpoint_id is None:
            raise ValueError("checkpoint_id is required for pending writes")
        key = checkpoint_writes_key(thread_id, checkpoint_ns, checkpoint_id)
        mapping = {
            f"{task_id}:{index}": json.dumps(
                {
                    "task_id": task_id,
                    "channel": channel,
                    "value": self._dump(value),
                    "task_path": task_path,
                }
            )
            for index, (channel, value) in enumerate(writes)
        }
        if not mapping:
            return
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def _load_pending_writes(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[tuple[str, str, Any]]:
        """读取并按字段名稳定排序中间写入。"""
        values = await self._client.hgetall(
            checkpoint_writes_key(thread_id, checkpoint_ns, checkpoint_id)
        )
        pending: list[tuple[str, str, Any]] = []
        for field in sorted(values):
            record = json.loads(values[field])
            pending.append(
                (
                    record["task_id"],
                    record["channel"],
                    self._load(record["value"]),
                )
            )
        return pending

    async def adelete_thread(self, thread_id: str) -> None:
        """删除指定线程的 Checkpoint；不触碰 Session 或 Conversation Key。"""
        registry_key = checkpoint_namespace_registry_key(thread_id)
        scopes = await self._client.smembers(registry_key)
        keys_to_delete: list[str] = [registry_key]
        for scope in scopes:
            index_key = f"{scope}:index"
            checkpoint_ids = await self._client.zrange(index_key, 0, -1)
            keys_to_delete.append(index_key)
            for checkpoint_id in checkpoint_ids:
                keys_to_delete.extend(
                    [
                        f"{scope}:data:{checkpoint_id}",
                        f"{scope}:writes:{checkpoint_id}",
                    ]
                )
        if keys_to_delete:
            await self._client.delete(*keys_to_delete)
