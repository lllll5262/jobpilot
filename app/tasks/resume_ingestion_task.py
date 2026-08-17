"""从 MinIO 消费原始 PDF 并完成简历入库。"""

import asyncio
from contextlib import suppress
from typing import Any

from app.api.dependencies import get_llm_client
from app.core.config import get_settings
from app.db.database import async_session_factory, dispose_database
from app.parsers.pdf_parser import PDFParser
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.services.resume_parser_service import ResumeParserService
from app.services.resume_storage_service import ResumeStorageService
from app.storage.dependencies import get_resume_object_store
from app.storage.resume_object_store import ResumeObjectMetadata
from app.tasks.celery_app import celery_app
from app.tasks.resume_ingestion_queue import TASK_NAME
from app.vectorstore.dependencies import get_resume_knowledge_service


@celery_app.task(name=TASK_NAME)
def ingest_resume(
    *,
    user_id: int,
    filename: str,
    doc_hash: str,
    stored_object: dict[str, Any],
) -> dict[str, Any]:
    """同步 Celery Task 包装异步应用服务，消息中不携带 PDF 二进制。"""
    return asyncio.run(
        _ingest_resume(
            user_id=user_id,
            filename=filename,
            doc_hash=doc_hash,
            stored_object=stored_object,
        )
    )


async def _ingest_resume(
    *,
    user_id: int,
    filename: str,
    doc_hash: str,
    stored_object: dict[str, Any],
) -> dict[str, Any]:
    metadata = ResumeObjectMetadata(**stored_object)
    object_store = get_resume_object_store()
    try:
        content = await object_store.read(
            bucket=metadata.bucket,
            object_key=metadata.object_key,
        )
        settings = get_settings()
        parser_service = ResumeParserService(
            PDFParser(max_pages=settings.resume_max_pages),
            get_llm_client(None),
            max_text_chars=settings.resume_max_text_chars,
        )
        async with async_session_factory() as session:
            service = ResumeStorageService(
                parser_service,
                ResumeRepository(session),
                UserRepository(session),
                get_resume_knowledge_service(),
                object_store,
            )
            record = await service.parse_staged_and_save(
                user_id=user_id,
                filename=filename,
                pdf_content=content,
                doc_hash=doc_hash,
                stored_object=metadata,
            )
        return {
            "user_id": user_id,
            "resume": record.model_dump(mode="json"),
        }
    except Exception:
        with suppress(Exception):
            await object_store.delete_resume(
                bucket=metadata.bucket,
                pdf_object_key=metadata.object_key,
            )
        raise
    finally:
        # 每个同步 Celery Task 使用独立事件循环，避免连接池跨事件循环复用。
        await dispose_database()
