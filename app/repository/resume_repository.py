"""简历 Repository。"""

from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resume import Resume


class ResumeRepository:
    """封装 resumes 表的数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, resume_id: int, *, user_id: int) -> Resume | None:
        """按用户边界获取指定 Resume。"""
        statement = select(Resume).where(
            Resume.id == resume_id,
            Resume.user_id == user_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_latest(self, user_id: int) -> Resume | None:
        """获取用户最新 Resume。"""
        statement = (
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(desc(Resume.created_at), desc(Resume.id))
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        filename: str,
        doc_hash: str,
        file_size_bytes: int,
        content_type: str,
        storage_bucket: str,
        storage_object_key: str,
        storage_uri: str,
        object_etag: str | None,
        parsed_data: dict[str, Any],
    ) -> Resume:
        """保存 MinIO 地址、文件校验信息和结构化 Resume。"""
        resume = Resume(
            user_id=user_id,
            filename=filename,
            doc_hash=doc_hash,
            file_size_bytes=file_size_bytes,
            content_type=content_type,
            storage_bucket=storage_bucket,
            storage_object_key=storage_object_key,
            storage_uri=storage_uri,
            object_etag=object_etag,
            parsed_data=parsed_data,
        )
        self._session.add(resume)
        await self._session.commit()
        await self._session.refresh(resume)
        return resume

    async def delete(self, resume_id: int, *, user_id: int) -> None:
        """删除一次未完成跨存储写入产生的关系型记录。"""
        await self._session.execute(
            delete(Resume).where(
                Resume.id == resume_id,
                Resume.user_id == user_id,
            )
        )
        await self._session.commit()
