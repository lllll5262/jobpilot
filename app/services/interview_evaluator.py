"""面试回答评价服务。"""

from app.llm.client import JSONGenerator
from app.llm.prompts.interview import (
    build_evaluation_system_prompt,
    build_evaluation_user_prompt,
)
from app.schemas.interview import InterviewEvaluationDraft, InterviewQuestion
from app.services.structured_output import generate_structured_output


class InterviewEvaluator:
    """将开放式用户回答转换为经过 Pydantic 校验的评价。"""

    def __init__(self, llm_client: JSONGenerator) -> None:
        self._llm_client = llm_client

    async def evaluate(
        self,
        *,
        question: InterviewQuestion,
        answer: str,
        raw_jd: str,
    ) -> InterviewEvaluationDraft:
        """返回分数、具体错误、改进点、薄弱点和正确答案。"""
        return await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_evaluation_system_prompt(),
            user_prompt=build_evaluation_user_prompt(
                question=question.model_dump(mode="json"),
                answer=answer,
                raw_jd=raw_jd,
            ),
            schema=InterviewEvaluationDraft,
            log_context="interview_evaluation",
            validation_retries=1,
        )
