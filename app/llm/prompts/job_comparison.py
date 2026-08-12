"""岗位对比和技能差距分析 Prompt。"""

import json
from typing import Any


def build_job_comparison_system_prompt() -> str:
    """限制 LLM 只解释差距，不参与算分和排序。"""
    return """你是 JobPilot 的岗位差距分析器。
Python 规则引擎已经计算并排序岗位，你不能修改分数、排名或推荐岗位。
请严格输出 JSON 对象，且只能包含：
- job_insights: 每个输入岗位一项，字段为 job_id、advantages、disadvantages、skill_gap_actions
- recommendation_reason: 解释排名第一岗位为什么更适合候选人

每个岗位必须且只能出现一次。分析应基于提供的 Profile、岗位要求和规则匹配结果，
不得编造候选人经历。skill_gap_actions 应具体说明需要补齐的技能或证据。"""


def build_job_comparison_user_prompt(
    *,
    profile: dict[str, Any],
    jobs: list[dict[str, Any]],
    recommended_job_id: int,
) -> str:
    """将已确定的规则结果作为不可修改的分析上下文。"""
    payload = {
        "candidate_profile": profile,
        "jobs_in_rule_order": jobs,
        "recommended_job_id": recommended_job_id,
    }
    return json.dumps(payload, ensure_ascii=False)
