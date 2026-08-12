"""历史或新粘贴岗位的比较编排服务。"""

from dataclasses import dataclass

from app.schemas.comparison import (
    ComparisonJobSource,
    JobComparisonItem,
    JobComparisonResult,
)
from app.schemas.persistence import AnalysisDraft, JobRecord
from app.schemas.profile import CandidateProfile
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.job_storage_service import JobStorageService


@dataclass(frozen=True, slots=True)
class ResolvedJob:
    """已经解析并持久化、可以进入规则匹配的岗位。"""

    record: JobRecord
    display_name: str


class JobCompareService:
    """解析岗位来源，复用匹配规则，并按 Python 分数生成最终排名。"""

    def __init__(
        self,
        *,
        job_service: JobStorageService,
        analysis_service: AnalysisStorageService,
        gap_analysis_service: GapAnalysisService,
    ) -> None:
        self._job_service = job_service
        self._analysis_service = analysis_service
        self._gap_analysis_service = gap_analysis_service

    async def compare(
        self,
        *,
        user_id: int,
        sources: list[ComparisonJobSource],
        profile: CandidateProfile,
    ) -> JobComparisonResult:
        """比较 2～5 个岗位；粘贴的 JD 会先解析并保存到历史记录。"""
        resolved = await self._resolve_jobs(user_id=user_id, sources=sources)
        drafts = await self._analysis_service.calculate_many(
            user_id=user_id,
            job_ids=[job.record.id for job in resolved],
        )
        ranked_pairs = sorted(
            enumerate(zip(resolved, drafts, strict=True)),
            key=lambda pair: (-pair[1][1].result.match_score, pair[0]),
        )
        ranked = [pair for _, pair in ranked_pairs]
        recommended_job_id = ranked[0][0].record.id
        contexts = [self._build_gap_context(job, draft) for job, draft in ranked]
        assessment = await self._gap_analysis_service.analyze(
            profile=profile,
            jobs=contexts,
            recommended_job_id=recommended_job_id,
        )
        insights = {item.job_id: item for item in assessment.job_insights}
        comparisons = []
        for rank, (job, draft) in enumerate(ranked, start=1):
            insight = insights[job.record.id]
            match = draft.result
            comparisons.append(
                JobComparisonItem(
                    rank=rank,
                    job_id=job.record.id,
                    job=job.display_name,
                    score=match.match_score,
                    recommendation=match.recommendation,
                    matched_skills=match.matched_skills,
                    missing_skills=match.missing_skills,
                    strong_points=match.strong_points,
                    weak_points=match.weak_points,
                    advantages=insight.advantages,
                    disadvantages=insight.disadvantages,
                    skill_gap_actions=insight.skill_gap_actions,
                )
            )
        return JobComparisonResult(
            recommended_job_id=recommended_job_id,
            recommended_job=comparisons[0].job,
            comparisons=comparisons,
            reason=assessment.recommendation_reason,
        )

    async def _resolve_jobs(
        self,
        *,
        user_id: int,
        sources: list[ComparisonJobSource],
    ) -> list[ResolvedJob]:
        """批量读取历史 JD，并将新粘贴 JD 解析后保存。"""
        historical_ids = [source.job_id for source in sources if source.job_id is not None]
        historical = await self._job_service.get_many(
            user_id=user_id,
            job_ids=historical_ids,
        )
        history_by_id = {record.id: record for record in historical}
        result: list[ResolvedJob] = []
        for source in sources:
            if source.job_id is not None:
                record = history_by_id[source.job_id]
            else:
                record = await self._job_service.parse_and_save(
                    user_id=user_id,
                    jd_text=source.jd_text or "",
                )
            result.append(
                ResolvedJob(
                    record=record,
                    display_name=self._display_name(source.label, record.job.job_title),
                )
            )
        return result

    @staticmethod
    def _display_name(label: str | None, job_title: str) -> str:
        """优先保留用户提供的公司标签，并补充结构化岗位名称。"""
        if label is None:
            return job_title
        if job_title.casefold() in label.casefold():
            return label
        return f"{label} {job_title}"

    @staticmethod
    def _build_gap_context(job: ResolvedJob, draft: AnalysisDraft) -> dict[str, object]:
        """只向差距分析模型提供经过校验的岗位和规则结果。"""
        return {
            "job_id": job.record.id,
            "job": job.display_name,
            "requirements": job.record.job.model_dump(mode="json"),
            "rule_match": draft.result.model_dump(mode="json"),
        }
