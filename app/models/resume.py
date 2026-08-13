"""简历 ORM Model。"""

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class Resume(CreatedAtMixin, Base):
    """保存 PDF 文件信息和结构化 Resume，不保存原始 PDF 二进制。"""

    __tablename__ = "resumes"
    __table_args__ = (Index("ix_resumes_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    parsed_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
