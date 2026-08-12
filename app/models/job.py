"""岗位 ORM Model。"""

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class Job(CreatedAtMixin, Base):
    """保存用户输入的原始 JD 和结构化岗位信息。"""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    parsed_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
