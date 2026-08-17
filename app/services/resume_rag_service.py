"""简历检索增强问答编排服务。"""

from app.core.exceptions import AppException
from app.llm.client import JSONGenerator
from app.llm.prompts.resume_rag import (
    build_resume_rag_system_prompt,
    build_resume_rag_user_prompt,
)
from app.schemas.resume_rag import ResumeAnswerResult, ResumeGroundedAnswerDraft
from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_storage_service import ResumeStorageService
from app.services.structured_output import generate_structured_output


class ResumeRagService:
    """检索简历父块，将其作为唯一事实来源交给 LLM。"""

    INSUFFICIENT_CONTEXT_ANSWER = "检索到的简历内容不足以回答该问题。"

    def __init__(
        self,
        *,
        llm_client: JSONGenerator,
        resume_service: ResumeStorageService,
    ) -> None:
        self._llm_client = llm_client
        self._resume_service = resume_service

    async def answer(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None = None,
    ) -> ResumeAnswerResult:
        """执行检索、父块去重、生成和引用校验。"""
        resume = await self._resume_service.get(user_id=user_id, resume_id=resume_id)
        effective_resume_id = resume.id
        matches = await self._resume_service.search_context(
            user_id=user_id,
            resume_id=effective_resume_id,
            query=query,
            limit=limit,
        )
        contexts = self._deduplicate_parents(matches)
        if not contexts:
            return ResumeAnswerResult(
                query=query,
                answer=self.INSUFFICIENT_CONTEXT_ANSWER,
                resume_id=effective_resume_id,
                cited_parent_ids=[],
                contexts=[],
            )

        draft = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_resume_rag_system_prompt(),
            user_prompt=build_resume_rag_user_prompt(
                query=query,
                contexts=[
                    {
                        "parent_id": match.parent_id,
                        "content": match.parent_content,
                    }
                    for match in contexts
                ],
            ),
            schema=ResumeGroundedAnswerDraft,
            log_context="resume_rag_answer",
            validation_retries=1,
        )

        available_parent_ids = {match.parent_id for match in contexts}
        cited_parent_ids = list(dict.fromkeys(draft.cited_parent_ids))
        has_invalid_citation = any(
            parent_id not in available_parent_ids for parent_id in cited_parent_ids
        )
        has_unsupported_answer = (
            not cited_parent_ids and draft.answer != self.INSUFFICIENT_CONTEXT_ANSWER
        )
        if has_invalid_citation or has_unsupported_answer:
            raise AppException(
                "LLM returned invalid resume citations",
                code=50240,
                status_code=502,
            )

        return ResumeAnswerResult(
            query=query,
            answer=draft.answer,
            resume_id=effective_resume_id,
            cited_parent_ids=cited_parent_ids,
            contexts=contexts,
        )

    @staticmethod
    def _deduplicate_parents(matches: list[ResumeChunkMatch]) -> list[ResumeChunkMatch]:
        """保留每个父块排名最高的命中，避免重复上下文影响生成与评估。"""
        unique: dict[str, ResumeChunkMatch] = {}
        for match in matches:
            unique.setdefault(match.parent_id, match)
        return list(unique.values())
