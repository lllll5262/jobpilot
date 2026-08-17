"""自适应面试业务服务。"""

from typing import Any

from app.core.exceptions import AppException
from app.llm.client import JSONGenerator
from app.llm.prompts.interview import build_question_system_prompt, build_question_user_prompt
from app.repository.interview_repository import InterviewRepository
from app.repository.job_repository import JobRepository
from app.repository.profile_repository import ProfileRepository
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.interview import (
    AnswerQuality,
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEvaluation,
    InterviewQuestion,
    InterviewQuestionDraft,
    InterviewRound,
    InterviewSessionRecord,
    InterviewStartRequest,
    InterviewWeakPointSummary,
    QuestionSource,
)
from app.schemas.job import JDParseResult
from app.schemas.profile import CandidateProfile
from app.services.interview_evaluator import InterviewEvaluator
from app.services.persistence_helpers import require_user
from app.services.resume_content_service import ResumeContentService
from app.services.structured_output import generate_structured_output


class InterviewService:
    """编排简历首问、答案评价、薄弱点追问和 JD 新问题。"""

    def __init__(
        self,
        *,
        llm_client: JSONGenerator,
        evaluator: InterviewEvaluator,
        interview_repository: InterviewRepository,
        job_repository: JobRepository,
        profile_repository: ProfileRepository,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
        resume_content_service: ResumeContentService,
    ) -> None:
        self._llm_client = llm_client
        self._evaluator = evaluator
        self._interview_repository = interview_repository
        self._job_repository = job_repository
        self._profile_repository = profile_repository
        self._resume_repository = resume_repository
        self._user_repository = user_repository
        self._resume_content_service = resume_content_service

    async def start(
        self,
        *,
        user_id: int,
        request: InterviewStartRequest,
    ) -> InterviewSessionRecord:
        """从当前 Profile 对应的简历生成第一道问题并保存。"""
        context = await self._load_context(user_id=user_id, job_id=request.job_id)
        first_question = await self._generate_question(
            source=QuestionSource.RESUME,
            sequence=1,
            context=context,
            rounds=[],
            weak_points=[],
        )
        rounds = [InterviewRound(sequence=1, question=first_question)]
        record = await self._interview_repository.create(
            user_id=user_id,
            resume_id=context["resume_record"].id,
            profile_id=context["profile_record"].id,
            job_id=context["job_record"].id,
            rounds_data=[round_.model_dump(mode="json") for round_ in rounds],
        )
        return self._to_record(record, context["job"].job_title)

    async def answer(
        self,
        *,
        user_id: int,
        session_id: int,
        request: InterviewAnswerRequest,
    ) -> InterviewAnswerResponse:
        """评价当前答案，按确定性规则追问或切换到 JD 新题。"""
        await require_user(self._user_repository, user_id)
        record = await self._interview_repository.get_by_id(
            session_id,
            user_id=user_id,
            for_update=True,
        )
        if record is None:
            raise AppException("Interview session not found", code=40410, status_code=404)
        context = await self._load_context(
            user_id=user_id,
            job_id=record.job_id,
            resume_id=record.resume_id,
            profile_id=record.profile_id,
        )
        rounds = [InterviewRound.model_validate(item) for item in record.rounds_data]
        current_round = rounds[-1]
        if current_round.evaluation is not None:
            raise AppException("Current question already answered", code=40911, status_code=409)
        if current_round.question.question_id != request.question_id:
            raise AppException("Interview question not found", code=40411, status_code=404)

        draft = await self._evaluator.evaluate(
            question=current_round.question,
            answer=request.answer,
            raw_jd=context["job_record"].raw_text,
        )
        evaluation = InterviewEvaluation(
            user_answer=request.answer,
            **draft.model_dump(),
        )
        rounds[-1] = current_round.model_copy(update={"evaluation": evaluation})
        weak_points = list(dict.fromkeys([*record.weak_points, *evaluation.weak_points]))

        # 面试不设置轮次上限：未掌握时紧扣本次回答追问，掌握后转向 JD 新主题。
        source = (
            QuestionSource.JD
            if evaluation.quality == AnswerQuality.MASTERED
            else QuestionSource.FOLLOW_UP
        )
        next_question = await self._generate_question(
            source=source,
            sequence=len(rounds) + 1,
            context=context,
            rounds=rounds,
            weak_points=weak_points,
        )
        rounds.append(
            InterviewRound(
                sequence=len(rounds) + 1,
                question=next_question,
            )
        )
        record = await self._interview_repository.update_progress(
            record,
            rounds_data=[round_.model_dump(mode="json") for round_ in rounds],
            weak_points=weak_points,
        )
        return InterviewAnswerResponse(
            evaluation=evaluation,
            next_question=next_question,
            session=self._to_record(record, context["job"].job_title),
        )

    async def get_session(self, *, user_id: int, session_id: int) -> InterviewSessionRecord:
        """读取已经汇总的题目、回答、错误和正确答案。"""
        await require_user(self._user_repository, user_id)
        record = await self._interview_repository.get_by_id(session_id, user_id=user_id)
        if record is None:
            raise AppException("Interview session not found", code=40410, status_code=404)
        job_record = await self._job_repository.get_by_id(record.job_id, user_id=user_id)
        if job_record is None:
            raise AppException("Job not found", code=40404, status_code=404)
        job = JDParseResult.model_validate(job_record.parsed_data)
        return self._to_record(record, job.job_title)

    async def request_topic(
        self,
        *,
        user_id: int,
        session_id: int,
        topic: str,
    ) -> InterviewQuestion:
        """按用户指定主题替换当前未作答题，不把控制指令当作答案评分。"""
        await require_user(self._user_repository, user_id)
        record = await self._interview_repository.get_by_id(
            session_id,
            user_id=user_id,
            for_update=True,
        )
        if record is None:
            raise AppException("Interview session not found", code=40410, status_code=404)
        context = await self._load_context(
            user_id=user_id,
            job_id=record.job_id,
            resume_id=record.resume_id,
            profile_id=record.profile_id,
        )
        rounds = [InterviewRound.model_validate(item) for item in record.rounds_data]
        current_round = rounds[-1]
        if current_round.evaluation is not None:
            raise AppException("No pending interview question", code=40912, status_code=409)
        rollback_misclassified_command = (
            len(rounds) >= 2
            and rounds[-2].evaluation is not None
            and self._is_topic_control(rounds[-2].evaluation.user_answer)
        )
        sequence = rounds[-2].sequence if rollback_misclassified_command else current_round.sequence
        question = await self._generate_question(
            source=QuestionSource.REQUESTED,
            sequence=sequence,
            context=context,
            rounds=rounds,
            weak_points=list(record.weak_points),
            requested_topic=topic,
        )
        if rollback_misclassified_command:
            rounds = [*rounds[:-2], InterviewRound(sequence=sequence, question=question)]
            weak_points = list(
                dict.fromkeys(
                    weak_point
                    for round_ in rounds
                    if round_.evaluation is not None
                    for weak_point in round_.evaluation.weak_points
                )
            )
        else:
            rounds[-1] = InterviewRound(sequence=sequence, question=question)
            weak_points = list(record.weak_points)
        await self._interview_repository.update_progress(
            record,
            rounds_data=[round_.model_dump(mode="json") for round_ in rounds],
            weak_points=weak_points,
        )
        return question

    @staticmethod
    def _is_topic_control(answer: str) -> bool:
        """识别曾被旧前端错误提交为答案的指定主题指令。"""
        return any(
            marker in answer.casefold()
            for marker in ("提问关于", "问我关于", "出题关于", "考察我关于")
        )

    async def get_weak_points(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> list[InterviewWeakPointSummary]:
        """用 Python 汇总出现次数和最近分数，不让 LLM 改写事实。"""
        session = await self.get_session(user_id=user_id, session_id=session_id)
        occurrences: dict[str, int] = {}
        latest_scores: dict[str, int] = {}
        for round_ in session.rounds:
            if round_.evaluation is None:
                continue
            for topic in round_.evaluation.weak_points:
                occurrences[topic] = occurrences.get(topic, 0) + 1
                latest_scores[topic] = round_.evaluation.score
        return [
            InterviewWeakPointSummary(
                topic=topic,
                occurrences=count,
                latest_score=latest_scores[topic],
            )
            for topic, count in occurrences.items()
        ]

    async def _generate_question(
        self,
        *,
        source: QuestionSource,
        sequence: int,
        context: dict[str, Any],
        rounds: list[InterviewRound],
        weak_points: list[str],
        requested_topic: str | None = None,
    ) -> InterviewQuestion:
        """生成一道符合指定来源的问题，并拒绝重复题目。"""
        draft = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_question_system_prompt(source=source.value),
            user_prompt=build_question_user_prompt(
                source=source.value,
                resume=context["resume"].model_dump(mode="json"),
                profile=context["profile"].model_dump(mode="json"),
                raw_jd=context["job_record"].raw_text,
                parsed_job=context["job"].model_dump(mode="json"),
                rounds=[round_.model_dump(mode="json") for round_ in rounds],
                weak_points=weak_points,
                requested_topic=requested_topic,
            ),
            schema=InterviewQuestionDraft,
            log_context=f"interview_question_{source.value}",
            validation_retries=1,
        )
        asked_questions = {round_.question.question.casefold() for round_ in rounds}
        if draft.question.casefold() in asked_questions:
            raise AppException(
                "LLM generated a duplicate interview question",
                code=50230,
                status_code=502,
            )
        return InterviewQuestion(
            question_id=f"q{sequence}",
            source=source,
            **draft.model_dump(),
        )

    async def _load_context(
        self,
        *,
        user_id: int,
        job_id: int,
        resume_id: int | None = None,
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        """读取并验证本场面试绑定的 Resume、Profile 和 Job。"""
        await require_user(self._user_repository, user_id)
        job_record = await self._job_repository.get_by_id(job_id, user_id=user_id)
        if job_record is None:
            raise AppException("Job not found", code=40404, status_code=404)
        profile_record = (
            await self._profile_repository.get_by_id(profile_id, user_id=user_id)
            if profile_id is not None
            else await self._profile_repository.get_current(user_id)
        )
        if profile_record is None:
            raise AppException("Interview profile is unavailable", code=40412, status_code=404)
        effective_resume_id = resume_id or profile_record.resume_id
        if effective_resume_id != profile_record.resume_id:
            raise AppException("Interview resume is unavailable", code=40413, status_code=404)
        resume_record = await self._resume_repository.get_by_id(
            effective_resume_id,
            user_id=user_id,
        )
        if resume_record is None:
            raise AppException("Resume not found", code=40402, status_code=404)
        return {
            "job_record": job_record,
            "profile_record": profile_record,
            "resume_record": resume_record,
            "job": JDParseResult.model_validate(job_record.parsed_data),
            "profile": CandidateProfile.model_validate(profile_record.profile_data),
            "resume": await self._resume_content_service.load(resume_record),
        }

    @staticmethod
    def _to_record(record: Any, job_title: str) -> InterviewSessionRecord:
        """计算平均分并构造 API DTO。"""
        rounds = [InterviewRound.model_validate(item) for item in record.rounds_data]
        scores = [round_.evaluation.score for round_ in rounds if round_.evaluation]
        current_question = rounds[-1].question if rounds[-1].evaluation is None else None
        return InterviewSessionRecord(
            id=record.id,
            user_id=record.user_id,
            resume_id=record.resume_id,
            profile_id=record.profile_id,
            job_id=record.job_id,
            job_title=job_title,
            rounds=rounds,
            weak_points=record.weak_points,
            average_score=round(sum(scores) / len(scores)) if scores else None,
            current_question=current_question,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
