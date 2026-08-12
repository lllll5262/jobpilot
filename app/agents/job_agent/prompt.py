"""Job Agent 系统提示词。"""

from app.schemas.agent import JobAgentToolName


def build_job_agent_system_prompt(next_tool: JobAgentToolName | None) -> str:
    """根据当前 Graph 状态约束模型调用唯一合法的下一步工具。"""
    workflow = (
        "get_candidate_profile → parse_job_description → "
        "calculate_job_match → save_analysis → Final Answer"
    )
    if next_tool is not None:
        instruction = (
            f"当前必须调用工具 {next_tool}。不要直接回答，不要调用其他工具，参数使用空对象。"
        )
    else:
        instruction = (
            "全部工具已经成功执行。请根据工具结果用中文给出最终结论，包含匹配分数、"
            "推荐结论、优势、缺失技能和改进建议，不要再调用工具。"
        )
    return (
        "你是 JobPilot 的 Job Agent，负责判断岗位是否适合当前候选人。"
        f"固定工作流为：{workflow}。{instruction}"
    )
