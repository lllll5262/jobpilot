"""岗位匹配编排服务。"""

import logging

from app.llm.client import JSONGenerator
from app.llm.prompts.match_analyzer import (
    build_match_system_prompt,
    build_match_user_prompt,
)
from app.rules.education_rules import evaluate_education
from app.rules.skill_rules import evaluate_skills
from app.schemas.job import JDParseResult
from app.schemas.match import MatchResult, SemanticMatchAssessment
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.scoring_service import ScoreInput, ScoringService
from app.services.structured_output import generate_structured_output

logger = logging.getLogger(__name__)


class MatchService:
    """组合语义分析与 Python Rule Engine，生成最终匹配结果。"""

    def __init__(self, llm_client: JSONGenerator, scoring_service: ScoringService) -> None:
        self._llm_client = llm_client
        self._scoring_service = scoring_service

    async def match(
        self,
        *,
        resume: ResumeParseResult,
        profile: CandidateProfile,
        job: JDParseResult,
    ) -> MatchResult:
        """让 LLM 负责语义，让规则引擎负责所有数值计算。"""
        semantic_assessment = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_match_system_prompt(),
            user_prompt=build_match_user_prompt(resume=resume, profile=profile, job=job),
            schema=SemanticMatchAssessment,
            log_context="match_analyzer",
        )

        skill_evaluation = evaluate_skills(
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            candidate_skills=profile.skills,
            semantic_matches=semantic_assessment.semantic_skill_matches,
        )
        education_fit = evaluate_education(job.education, resume.education)
        score_result = self._scoring_service.calculate(
            ScoreInput(
                required_skill_ratio=skill_evaluation.required_ratio,
                preferred_skill_ratio=skill_evaluation.preferred_ratio,
                project_relevance=semantic_assessment.project_relevance,
                experience_fit=semantic_assessment.experience_fit,
                education_fit=education_fit,
                experience_required=job.experience is not None,
            )
        )

        result = MatchResult(
            match_score=score_result.score,
            matched_skills=skill_evaluation.matched_skills,
            missing_skills=skill_evaluation.missing_skills,
            strong_points=semantic_assessment.strong_points,
            weak_points=semantic_assessment.weak_points,
            recommendation=score_result.recommendation,
        )
        logger.info(
            "岗位匹配完成 score=%s recommendation=%s matched=%s missing=%s",
            result.match_score,
            result.recommendation,
            len(result.matched_skills),
            len(result.missing_skills),
        )
        return result
