"""Job Agent 系统提示词。"""

import json

from app.schemas.agent import JobAgentToolName


def build_job_agent_system_prompt(
    next_tool: JobAgentToolName | None,
    analysis_context: list[dict[str, object]],
) -> str:
    """根据当前 Graph 状态约束模型调用唯一合法的下一步工具。"""
    analysis_workflow = (
        "get_candidate_profile → parse_job_description → "
        "calculate_job_match → save_analysis → Final Answer"
    )
    comparison_workflow = "get_candidate_profile → compare_jobs → Final Answer"
    if next_tool is not None:
        instruction = (
            f"当前必须调用工具 {next_tool}。不要直接回答，不要调用其他工具，参数使用空对象。"
        )
    else:
        instruction = (
            "请结合当前消息、最近对话和历史岗位分析，用中文回答。若本轮分析了新岗位，"
            "应包含匹配分数、推荐结论、优势、缺失技能和改进建议；若是比较追问，"
            "必须明确比较对象、规则分数、技能差距、岗位优缺点和推荐理由。"
            "不得修改 Tool 返回的分数、排名或推荐岗位。不要再调用工具。"
        )
    context = json.dumps(analysis_context, ensure_ascii=False)
    return (
        "你是 JobPilot 的 Job Agent，负责判断岗位是否适合当前候选人。"
        f"单岗位工作流：{analysis_workflow}；多岗位工作流：{comparison_workflow}。"
        f"{instruction}"
        f"最近岗位分析上下文：{context}"
    )
