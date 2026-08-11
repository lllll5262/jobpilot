"""候选人能力画像服务。"""

import logging

from app.llm.client import JSONGenerator
from app.llm.prompts.profile_builder import (
    build_profile_system_prompt,
    build_profile_user_prompt,
)
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.structured_output import generate_structured_output

logger = logging.getLogger(__name__)


class CandidateProfileService:
    """根据结构化 Resume 推导候选人能力，而不修改原始经历数据。"""

    def __init__(self, llm_client: JSONGenerator) -> None:
        self._llm_client = llm_client

    async def build(self, resume: ResumeParseResult) -> CandidateProfile:
        """构建并校验独立的 Candidate Profile。"""
        profile = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_profile_system_prompt(),
            user_prompt=build_profile_user_prompt(resume),
            schema=CandidateProfile,
            log_context="profile_builder",
        )
        logger.info(
            "候选人画像构建成功 skills_count=%s domains_count=%s",
            len(profile.skills),
            len(profile.domains),
        )
        return profile
