"""Supervisor Prompt 对外导出。"""

from app.llm.prompts.supervisor import (
    build_supervisor_system_prompt,
    build_supervisor_user_prompt,
)

__all__ = ["build_supervisor_system_prompt", "build_supervisor_user_prompt"]
