"""阶段 5 持久化分层测试，不连接真实 MySQL。"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import app.models  # noqa: F401  # 注册所有表到 Metadata。
from app.db.base import Base
from app.main import app
from app.schemas.job import JDParseResult
from app.schemas.match import MatchResult
from app.schemas.persistence import UserCreateRequest
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_parser_service import ParsedResumeDocument
from app.services.resume_storage_service import ResumeStorageService
from app.services.user_service import UserService

CREATED_AT = datetime(2026, 8, 12, tzinfo=UTC)

RESUME_DATA = {
    "personal_info": {
        "name": "测试用户",
        "email": "user@example.com",
        "phone": None,
        "location": None,
    },
    "education": [],
    "skills": ["Java"],
    "projects": [],
    "internships": [],
    "certificates": [],
}

PROFILE_DATA = {
    "skills": {"Java": "advanced"},
    "domains": ["后端开发"],
}

JOB_DATA = {
    "job_title": "Java后端工程师",
    "required_skills": ["Java"],
    "preferred_skills": [],
    "education": None,
    "experience": None,
}

MATCH_DATA = {
    "match_score": 100,
    "matched_skills": ["Java"],
    "missing_skills": [],
    "strong_points": ["Java 能力匹配"],
    "weak_points": [],
    "recommendation": "RECOMMEND",
}


class FakeUserRepository:
    """内存用户 Repository。"""

    def __init__(self) -> None:
        self.user: Any = None

    async def get_by_id(self, user_id: int) -> Any:
        return self.user if self.user and self.user.id == user_id else None

    async def get_by_email(self, email: str) -> Any:
        return self.user if self.user and self.user.email == email else None

    async def create(self, *, email: str, name: str | None) -> Any:
        self.user = SimpleNamespace(
            id=1,
            email=email,
            name=name,
            created_at=CREATED_AT,
        )
        return self.user


class FakeResumeRepository:
    """内存 Resume Repository。"""

    def __init__(self) -> None:
        self.record: Any = None

    async def create(
        self,
        *,
        user_id: int,
        filename: str,
        parsed_data: dict[str, Any],
    ) -> Any:
        self.record = SimpleNamespace(
            id=10,
            user_id=user_id,
            filename=filename,
            parsed_data=parsed_data,
            created_at=CREATED_AT,
        )
        return self.record

    async def get_by_id(self, resume_id: int, *, user_id: int) -> Any:
        if self.record and self.record.id == resume_id and self.record.user_id == user_id:
            return self.record
        return None

    async def delete(self, resume_id: int, *, user_id: int) -> None:
        if self.record and self.record.id == resume_id and self.record.user_id == user_id:
            self.record = None


class FakeProfileRepository:
    """内存 Profile Repository。"""

    def __init__(self) -> None:
        self.record: Any = None

    async def create_current(
        self,
        *,
        user_id: int,
        resume_id: int,
        profile_data: dict[str, Any],
    ) -> Any:
        self.record = SimpleNamespace(
            id=20,
            user_id=user_id,
            resume_id=resume_id,
            profile_data=profile_data,
            is_current=True,
            created_at=CREATED_AT,
        )
        return self.record

    async def get_current(self, user_id: int) -> Any:
        return self.record if self.record and self.record.user_id == user_id else None


class FakeJobRepository:
    """内存 Job Repository。"""

    def __init__(self) -> None:
        self.record: Any = None

    async def create(
        self,
        *,
        user_id: int,
        raw_text: str,
        parsed_data: dict[str, Any],
    ) -> Any:
        self.record = SimpleNamespace(
            id=30,
            user_id=user_id,
            raw_text=raw_text,
            parsed_data=parsed_data,
            created_at=CREATED_AT,
        )
        return self.record

    async def get_by_id(self, job_id: int, *, user_id: int) -> Any:
        if self.record and self.record.id == job_id and self.record.user_id == user_id:
            return self.record
        return None

    async def get_by_ids(self, job_ids: list[int], *, user_id: int) -> list[Any]:
        """模拟阶段 8 多岗位批量读取。"""
        record = await self.get_by_id(job_ids[0], user_id=user_id) if job_ids else None
        return [record] if record is not None and record.id in job_ids else []

    async def list_by_user(self, user_id: int, *, limit: int, offset: int) -> list[Any]:
        records = [self.record] if self.record and self.record.user_id == user_id else []
        return records[offset : offset + limit]


class FakeAnalysisRepository:
    """内存 JobAnalysis Repository。"""

    def __init__(self) -> None:
        self.record: Any = None

    async def create(self, **values: Any) -> Any:
        self.record = SimpleNamespace(id=40, created_at=CREATED_AT, **values)
        return self.record

    async def list_by_user(self, user_id: int, *, limit: int, offset: int) -> list[Any]:
        records = [self.record] if self.record and self.record.user_id == user_id else []
        return records[offset : offset + limit]


class StubResumeParserService:
    """固定返回结构化 Resume。"""

    async def parse_with_source(self, pdf_content: bytes) -> ParsedResumeDocument:
        """持久化流程还需要完整文本用于 MongoDB 和 Milvus。"""
        assert pdf_content.startswith(b"%PDF-")
        return ParsedResumeDocument(
            resume=ResumeParseResult.model_validate(RESUME_DATA),
            cleaned_text="测试用户 Java 后端开发简历",
        )


class FakeResumeKnowledgeService:
    """避免持久化闭环测试连接真实 MongoDB 和 Milvus。"""

    def __init__(self) -> None:
        self.saved_resume_id: int | None = None

    async def save(self, **values: Any) -> None:
        self.saved_resume_id = values["resume_id"]



class StubProfileBuilderService:
    """固定返回 Candidate Profile。"""

    async def build(self, resume: ResumeParseResult) -> CandidateProfile:
        assert "Java" in resume.skills
        return CandidateProfile.model_validate(PROFILE_DATA)


class StubJDParserService:
    """固定返回结构化 JD。"""

    async def parse(self, jd_text: str) -> JDParseResult:
        assert "Java" in jd_text
        return JDParseResult.model_validate(JOB_DATA)


class StubMatchService:
    """固定返回规则匹配结果。"""

    async def match(
        self,
        *,
        resume: ResumeParseResult,
        profile: CandidateProfile,
        job: JDParseResult,
    ) -> MatchResult:
        assert "Java" in resume.skills
        assert "Java" in profile.skills
        assert "Java" in job.required_skills
        return MatchResult.model_validate(MATCH_DATA)


def test_metadata_contains_stage5_tables() -> None:
    """后续阶段增加表时，阶段 5 的五张业务表仍必须保留。"""
    assert {
        "users",
        "resumes",
        "candidate_profiles",
        "jobs",
        "job_analyses",
    }.issubset(Base.metadata.tables)


def test_persistence_routes_are_registered() -> None:
    """OpenAPI 应暴露保存、历史查询和当前 Profile 接口。"""
    paths = app.openapi()["paths"]
    assert {
        "/users",
        "/users/{user_id}/resumes/parse",
        "/users/{user_id}/resumes/search",
        "/users/{user_id}/resumes/{resume_id}/source",
        "/users/{user_id}/profiles/build",
        "/users/{user_id}/profile",
        "/users/{user_id}/jobs/parse",
        "/users/{user_id}/jobs",
        "/users/{user_id}/job-analyses",
    }.issubset(paths)


def test_persistence_services_complete_closed_loop() -> None:
    """所有持久化 Service 应通过 Repository 完成首个闭环。"""

    async def run_workflow() -> None:
        user_repository = FakeUserRepository()
        resume_repository = FakeResumeRepository()
        profile_repository = FakeProfileRepository()
        job_repository = FakeJobRepository()
        analysis_repository = FakeAnalysisRepository()

        user = await UserService(user_repository).create(
            UserCreateRequest(email="USER@example.com", name="测试用户")
        )
        assert user.email == "user@example.com"

        resume_service = ResumeStorageService(
            StubResumeParserService(),
            resume_repository,
            user_repository,
            FakeResumeKnowledgeService(),  # type: ignore[arg-type]
        )
        resume = await resume_service.parse_and_save(
            user_id=user.id,
            filename="resume.pdf",
            pdf_content=b"%PDF-test",
        )
        assert resume.resume.skills == ["Java"]

        profile_service = ProfileStorageService(
            StubProfileBuilderService(),
            profile_repository,
            resume_repository,
            user_repository,
        )
        profile = await profile_service.build_and_save(
            user_id=user.id,
            resume_id=resume.id,
        )
        assert profile.is_current is True
        assert (await profile_service.get_current(user.id)).id == profile.id

        job_service = JobStorageService(
            StubJDParserService(),
            job_repository,
            user_repository,
        )
        job = await job_service.parse_and_save(
            user_id=user.id,
            jd_text="Java后端工程师",
        )
        assert (await job_service.list_history(user.id, limit=20, offset=0))[0].id == job.id

        analysis_service = AnalysisStorageService(
            StubMatchService(),
            analysis_repository,
            job_repository,
            profile_repository,
            resume_repository,
            user_repository,
        )
        analysis = await analysis_service.analyze_and_save(
            user_id=user.id,
            job_id=job.id,
        )
        assert analysis.result.match_score == 100
        history = await analysis_service.list_history(user.id, limit=20, offset=0)
        assert history[0].id == analysis.id

    asyncio.run(run_workflow())
