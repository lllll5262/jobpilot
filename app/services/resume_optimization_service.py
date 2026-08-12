"""Resume Agent 针对历史岗位生成事实受限的简历建议。"""

import re

from app.llm.client import JSONGenerator
from app.llm.prompts.resume_agent import (
    build_resume_optimization_system_prompt,
    build_resume_optimization_user_prompt,
)
from app.schemas.resume import ResumeParseResult
from app.schemas.resume_agent import (
    ResumeOptimizationDraft,
    ResumeOptimizationResult,
    ResumeOptimizationSuggestion,
)
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_storage_service import ResumeStorageService
from app.services.structured_output import generate_structured_output


class ResumeOptimizationService:
    """协调 Resume、Profile、Job，但不直接修改数据库中的简历。"""

    def __init__(
        self,
        *,
        llm_client: JSONGenerator,
        resume_service: ResumeStorageService,
        profile_service: ProfileStorageService,
        job_service: JobStorageService,
    ) -> None:
        self._llm_client = llm_client
        self._resume_service = resume_service
        self._profile_service = profile_service
        self._job_service = job_service

    async def optimize(
        self,
        *,
        user_id: int,
        resume_id: int | None,
        job_id: int,
    ) -> ResumeOptimizationResult:
        """生成建议；因未保存 PDF 原文，结果仅覆盖结构化 Resume。"""
        profile = await self._profile_service.get_current(user_id)
        effective_resume_id = resume_id or profile.resume_id
        resume = await self._resume_service.get(
            user_id=user_id,
            resume_id=effective_resume_id,
        )
        job = (await self._job_service.get_many(user_id=user_id, job_ids=[job_id]))[0]
        draft = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_resume_optimization_system_prompt(),
            user_prompt=build_resume_optimization_user_prompt(
                resume=resume.resume.model_dump(mode="json"),
                profile=profile.profile.model_dump(mode="json"),
                job=job.job.model_dump(mode="json"),
            ),
            schema=ResumeOptimizationDraft,
            log_context="resume_agent_optimization",
            validation_retries=1,
        )
        suggestions, rejected_locations = self._filter_supported_suggestions(
            resume=resume.resume,
            suggestions=draft.suggestions,
        )
        issues = list(draft.issues)
        if rejected_locations:
            issues.append(
                "以下修改未能准确对应结构化简历原文，已被系统过滤："
                + "、".join(rejected_locations)
            )
        return ResumeOptimizationResult(
            resume_id=resume.id,
            profile_id=profile.id,
            job_id=job.id,
            project_analysis=draft.project_analysis,
            issues=issues,
            suggestions=suggestions,
            limitation="仅基于数据库保存的结构化简历，不包含原始 PDF 全文和排版。",
        )

    @staticmethod
    def _filter_supported_suggestions(
        *,
        resume: ResumeParseResult,
        suggestions: list[ResumeOptimizationSuggestion],
    ) -> tuple[list[ResumeOptimizationSuggestion], list[str]]:
        """只保留位置和原文都能对应结构化简历的建议。"""
        source_texts = {"skills": "、".join(resume.skills)}
        source_texts.update(
            {
                f"projects[{index}].description": project.description
                for index, project in enumerate(resume.projects)
                if project.description
            }
        )
        source_texts.update(
            {
                f"internships[{index}].description": internship.description
                for index, internship in enumerate(resume.internships)
                if internship.description
            }
        )
        accepted: list[ResumeOptimizationSuggestion] = []
        rejected: list[str] = []
        for suggestion in suggestions:
            source_text = source_texts.get(suggestion.location)
            if source_text is None or ResumeOptimizationService._normalize_text(
                source_text
            ) != ResumeOptimizationService._normalize_text(suggestion.original_text):
                rejected.append(suggestion.location)
                continue
            # 输出时恢复数据库里的准确原文，避免 LLM 对换行或空格做出的无意义改动。
            accepted.append(suggestion.model_copy(update={"original_text": source_text}))
        return accepted, rejected

    @staticmethod
    def _normalize_text(value: str) -> str:
        """仅折叠空白差异，事实内容仍必须与结构化简历一致。"""
        return re.sub(r"\s+", "", value)
