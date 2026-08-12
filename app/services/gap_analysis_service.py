"""多岗位技能差距语义分析服务。"""

from app.core.exceptions import AppException
from app.llm.client import JSONGenerator
from app.llm.prompts.job_comparison import (
    build_job_comparison_system_prompt,
    build_job_comparison_user_prompt,
)
from app.schemas.comparison import ComparisonSemanticAssessment
from app.schemas.profile import CandidateProfile
from app.services.structured_output import generate_structured_output


class GapAnalysisService:
    """让 LLM 解释优缺点和补齐动作，不参与规则算分。"""

    def __init__(self, llm_client: JSONGenerator) -> None:
        self._llm_client = llm_client

    async def analyze(
        self,
        *,
        profile: CandidateProfile,
        jobs: list[dict[str, object]],
        recommended_job_id: int,
    ) -> ComparisonSemanticAssessment:
        """生成结构化差距分析，并校验岗位集合未被模型篡改。"""
        assessment = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_job_comparison_system_prompt(),
            user_prompt=build_job_comparison_user_prompt(
                profile=profile.model_dump(mode="json"),
                jobs=jobs,
                recommended_job_id=recommended_job_id,
            ),
            schema=ComparisonSemanticAssessment,
            log_context="job_comparison",
        )
        expected_ids = {int(job["job_id"]) for job in jobs}
        actual_ids = [insight.job_id for insight in assessment.job_insights]
        if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
            raise AppException(
                "LLM output failed schema validation",
                code=50202,
                status_code=502,
            )
        return assessment
