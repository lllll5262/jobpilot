"""岗位分析 ORM Model。"""

from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class JobAnalysis(CreatedAtMixin, Base):
    """关联 Resume、Profile、JD，并保存最终规则计算结果。"""

    __tablename__ = "job_analyses"
    __table_args__ = (
        Index("ix_job_analyses_user_created", "user_id", "created_at"),
        CheckConstraint("match_score BETWEEN 0 AND 100", name="match_score_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    resume_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    result_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
