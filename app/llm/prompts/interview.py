"""自适应面试的问题生成和答案评价 Prompt。"""

import json
from typing import Any

from app.schemas.interview import InterviewEvaluationDraft, InterviewQuestionDraft


def build_question_system_prompt(*, source: str) -> str:
    """根据题目来源限制模型只能使用对应事实生成一道题。"""
    schema = json.dumps(InterviewQuestionDraft.model_json_schema(), ensure_ascii=False)
    source_rules = {
        "resume": "第一题必须基于简历中的一个已有项目、技能或经历，询问具体实现或原理。",
        "follow_up": (
            "必须针对用户上一轮回答暴露的错误、遗漏或薄弱点追问，"
            "不能切换到无关主题，也不能重复上一题。"
        ),
        "jd": "必须从 JD 尚未充分考察的技能或职责中选择一个新主题提问。",
        "requested": (
            "必须严格围绕用户指定的 requested_topic 提问；可以问通用技术原理，"
            "但不得声称候选人拥有上下文中不存在的项目经历。"
        ),
    }
    example = {
        "topic": "Redis 高并发",
        "question": "你在项目中如何处理缓存击穿？",
        "focus_points": ["互斥锁", "逻辑过期"],
        "source_basis": "简历中的 Redis 项目经历",
    }
    return f"""你是 JobPilot 的技术面试官，一次只生成一道问题。
当前问题来源为 {source}。
{source_rules[source]}

规则：
1. 不得虚构简历中不存在的经历。
2. question 必须清晰、具体、可以通过文字回答。
3. focus_points 只列评分关键点，不能在 question 中泄露答案。
4. source_basis 简要说明该题依据了哪段简历、哪条回答或哪项 JD 要求。
5. 只返回 JSON，不返回 Markdown 或额外说明。

返回示例：
{json.dumps(example, ensure_ascii=False)}

严格符合以下 JSON Schema：
{schema}"""


def build_question_user_prompt(
    *,
    source: str,
    resume: dict[str, Any],
    profile: dict[str, Any],
    raw_jd: str,
    parsed_job: dict[str, Any],
    rounds: list[dict[str, Any]],
    weak_points: list[str],
    requested_topic: str | None = None,
) -> str:
    """按来源裁剪上下文，追问时保留上一轮真实回答和评价。"""
    payload: dict[str, Any] = {
        "source": source,
        "candidate_profile": profile,
        "asked_topics": [item["question"]["topic"] for item in rounds],
        "known_weak_points": weak_points,
    }
    if source == "resume":
        payload["resume"] = resume
    elif source == "follow_up":
        payload["previous_round"] = rounds[-1]
    elif source == "jd":
        payload["raw_job_description"] = raw_jd
        payload["parsed_job"] = parsed_job
    else:
        payload["requested_topic"] = requested_topic
        payload["resume"] = resume
        payload["raw_job_description"] = raw_jd
        payload["parsed_job"] = parsed_job
    return json.dumps(payload, ensure_ascii=False)


def build_evaluation_system_prompt() -> str:
    """评价用户回答并输出明确错误与正确答案。"""
    schema = json.dumps(InterviewEvaluationDraft.model_json_schema(), ensure_ascii=False)
    example = {
        "score": 55,
        "quality": "partial",
        "errors": ["遗漏了失败补偿处理"],
        "improvements": ["补充缓存删除失败后的重试方案"],
        "weak_points": ["缓存一致性"],
        "correct_answer": "更新数据库后删除缓存，失败时通过重试或可靠消息补偿。",
    }
    return f"""你是 JobPilot 的技术面试官，请评价用户对当前题目的回答。

规则：
1. score 为 0 到 100 的整数。
2. quality 只能是 incorrect、partial、mastered：核心结论错误为 incorrect；
   方向正确但有重要遗漏为 partial；核心结论正确且关键点覆盖充分才是 mastered。
3. errors 必须指出事实错误、逻辑错误或关键遗漏；没有错误时返回空数组。
4. improvements 给出如何把回答组织得更完整，不能泛泛而谈。
5. weak_points 只记录本次回答真实暴露的知识薄弱点。
6. correct_answer 必须直接、准确、完整地回答当前问题。
7. 不因为措辞不同而判错，依据 question.focus_points 和技术事实评价。
8. 只返回 JSON，不返回 Markdown 或额外说明。

返回示例：
{json.dumps(example, ensure_ascii=False)}

严格符合以下 JSON Schema：
{schema}"""


def build_evaluation_user_prompt(
    *,
    question: dict[str, Any],
    answer: str,
    raw_jd: str,
) -> str:
    """传递评价所需的题目、用户原回答和岗位语境。"""
    return json.dumps(
        {
            "question": question,
            "user_answer": answer,
            "job_context": raw_jd,
        },
        ensure_ascii=False,
    )
