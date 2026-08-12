"""Job Agent Tool 的公共协议和结果类型。"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from app.core.exceptions import AppException
from app.schemas.agent import JobAgentToolName


class AgentExecutionError(AppException):
    """模型未遵循工具协议或 Agent 状态不完整。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=50220, status_code=502)


@dataclass(frozen=True, slots=True)
class AgentToolResult:
    """一次工具执行产生的模型可见内容和 Graph 状态更新。"""

    content: dict[str, Any]
    state_updates: dict[str, Any]


class BaseAgentTool(ABC):
    """Tool 只负责适配 Agent 状态和已有 Service。"""

    name: ClassVar[JobAgentToolName]
    description: ClassVar[str]

    @property
    def definition(self) -> dict[str, Any]:
        """生成 OpenAI-compatible Function Tool 定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                # 用户与流程数据来自可信 Graph State，不允许模型篡改。
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }

    @abstractmethod
    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """调用已有业务 Service，并返回需要写入 Graph 的状态。"""

    @staticmethod
    def ensure_no_arguments(arguments: dict[str, Any]) -> None:
        """阶段 6 工具参数全部从可信 State 注入。"""
        if arguments:
            raise AgentExecutionError("Tool arguments must be empty")
