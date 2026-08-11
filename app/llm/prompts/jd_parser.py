"""JD 解析 Prompt。"""

import json

from app.schemas.job import JDParseResult


def build_jd_parser_system_prompt() -> str:
    """使用 Pydantic JSON Schema 构建唯一可信的输出约束。"""
    output_schema = json.dumps(
        JDParseResult.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return f"""
你是专业的职位描述（JD）信息抽取器。
你的唯一任务是从用户提供的 JD 文本中提取信息，并仅输出合法 JSON 对象。

规则：
1. required_skills 只包含明确要求、必须、掌握或熟悉的技能。
2. preferred_skills 只包含优先、加分、最好具备或非必需的技能。
3. 不得根据常识补充原文没有提到的信息。
4. 原文未提及学历或经验时，对应字段输出 null。
5. 所有字段必须存在，不要输出 Markdown、解释或额外字段。

输出必须符合以下 JSON Schema：
{output_schema}
""".strip()


def build_jd_parser_user_prompt(jd_text: str) -> str:
    """将用户输入明确标记为待解析数据，降低指令混淆。"""
    return f"请将以下 JD 解析为 JSON：\n\n<jd>\n{jd_text}\n</jd>"
