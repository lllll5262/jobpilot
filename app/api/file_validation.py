"""上传文件的共享校验逻辑。"""

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import AppException

ALLOWED_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


async def read_validated_pdf(file: UploadFile, settings: Settings) -> tuple[str, bytes]:
    """校验 PDF 元数据、大小和文件签名，并关闭上传文件。"""
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise AppException("Only PDF files are supported", code=40010, status_code=400)
    if len(filename) > 255:
        raise AppException("PDF filename is too long", code=40013, status_code=400)
    if file.content_type not in ALLOWED_PDF_CONTENT_TYPES:
        raise AppException("Invalid PDF content type", code=40011, status_code=400)

    max_bytes = settings.resume_max_file_size_mb * 1024 * 1024
    try:
        content = await file.read(max_bytes + 1)
    finally:
        await file.close()

    if len(content) > max_bytes:
        raise AppException(
            f"PDF file exceeds the {settings.resume_max_file_size_mb} MB limit",
            code=41301,
            status_code=413,
        )
    if not content.startswith(b"%PDF-"):
        raise AppException("Invalid PDF file signature", code=40012, status_code=400)
    return filename, content
