"""Resume Agent 项目分析和针对性优化 Prompt。"""

import json
from typing import Any

from app.schemas.resume_agent import ResumeOptimizationDraft


def build_resume_optimization_system_prompt() -> str:
    """只允许根据结构化 Resume 的已有事实生成建议。"""
    schema = json.dumps(ResumeOptimizationDraft.model_json_schema(), ensure_ascii=False)
    return f"""你是 JobPilot Resume Agent 的简历优化器。
根据结构化 Resume、Candidate Profile 和目标 JD 分析项目经历并提出修改建议。

必须遵守：
1. 禁止新增 Resume 中不存在的项目、实习、技能、成果或量化数据。
2. original_text 必须逐字复制结构化 Resume 中的已有非空文本。
3. location 使用 skills、projects[n].description 或 internships[n].description，n 从 0 开始。
4. 如果没有可以安全改写的原文，只写入 issues，不生成对应 suggestion。
5. suggested_text 可以改善表达，但不得把 JD 中缺少证据的技术写成候选人已掌握。
6. 只返回 JSON，不返回 Markdown 或额外说明。

严格符合以下 JSON Schema：
{schema}"""


def build_resume_optimization_user_prompt(
    *,
    resume: dict[str, Any],
    profile: dict[str, Any],
    job: dict[str, Any],
) -> str:
    """传递已通过 Pydantic 校验的三个领域对象。"""
    return json.dumps(
        {
            "resume": resume,
            "candidate_profile": profile,
            "target_job": job,
        },
        ensure_ascii=False,
    )
