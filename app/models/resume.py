"""简历 ORM Model。"""

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class Resume(CreatedAtMixin, Base):
    """保存 MinIO 对象元数据和结构化 Resume，不保存原始 PDF 二进制。"""

    __tablename__ = "resumes"
    __table_args__ = (
        Index("ix_resumes_user_created", "user_id", "created_at"),
        Index(
            "uq_resumes_storage_object",
            "storage_bucket",
            "storage_object_key",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    storage_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    object_etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parsed_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
