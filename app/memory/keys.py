"""集中管理 Redis Key，避免不同数据类型相互覆盖。"""

from hashlib import sha256

PREFIX = "jobpilot"


def _digest(value: str) -> str:
    """将外部标识转换为固定长度 Key 片段。"""
    return sha256(value.encode("utf-8")).hexdigest()[:32]


def session_key(session_id: str) -> str:
    """会话元数据 Key。"""
    return f"{PREFIX}:session:{_digest(session_id)}"


def session_turn_key(session_id: str) -> str:
    """会话轮次计数器 Key。"""
    return f"{PREFIX}:session:{_digest(session_id)}:turn"


def conversation_key(session_id: str) -> str:
    """最近 N 轮对话列表 Key。"""
    return f"{PREFIX}:memory:{_digest(session_id)}:messages"


def analysis_cache_key(session_id: str) -> str:
    """供比较追问使用的最近岗位分析缓存 Key。"""
    return f"{PREFIX}:cache:{_digest(session_id)}:analyses"


def checkpoint_scope(thread_id: str, checkpoint_ns: str) -> str:
    """LangGraph Checkpoint 的线程与命名空间前缀。"""
    return f"{PREFIX}:checkpoint:{_digest(thread_id)}:{_digest(checkpoint_ns)}"


def checkpoint_key(thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
    """单个 LangGraph Checkpoint Key。"""
    return f"{checkpoint_scope(thread_id, checkpoint_ns)}:data:{checkpoint_id}"


def checkpoint_writes_key(thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
    """Checkpoint 中间写入 Hash Key。"""
    return f"{checkpoint_scope(thread_id, checkpoint_ns)}:writes:{checkpoint_id}"


def checkpoint_index_key(thread_id: str, checkpoint_ns: str) -> str:
    """按写入时间排序的 Checkpoint 索引。"""
    return f"{checkpoint_scope(thread_id, checkpoint_ns)}:index"


def checkpoint_namespace_registry_key(thread_id: str) -> str:
    """线程拥有的命名空间索引集合。"""
    return f"{PREFIX}:checkpoint:{_digest(thread_id)}:namespaces"
