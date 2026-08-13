"""候选人能力画像 ORM Model。"""

from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class CandidateProfile(CreatedAtMixin, Base):
    """保存由某份 Resume 构建的能力画像及当前版本标记。"""

    __tablename__ = "candidate_profiles"
    __table_args__ = (Index("ix_candidate_profiles_user_current", "user_id", "is_current"),)

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
    profile_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("1"),
    )
