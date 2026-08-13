"""基于 PyMuPDF 的文本型 PDF 解析器。"""

import pymupdf

from app.parsers.base import (
    BaseDocumentParser,
    DocumentLimitError,
    DocumentParserError,
    EncryptedDocumentError,
    ParsedDocument,
)


class PDFParser(BaseDocumentParser):
    """仅提取 PDF 内已有文本，不执行 OCR。"""

    def __init__(self, *, max_pages: int) -> None:
        self._max_pages = max_pages

    def parse(self, content: bytes) -> ParsedDocument:
        """逐页提取文本，并拒绝加密或页数超限的 PDF。"""
        try:
            document = pymupdf.open(stream=content, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise DocumentParserError("Invalid PDF document") from exc

        with document:
            if document.needs_pass:
                raise EncryptedDocumentError("Encrypted PDF is not supported")
            if document.page_count > self._max_pages:
                raise DocumentLimitError(f"PDF page count exceeds the limit of {self._max_pages}")

            try:
                pages = [page.get_text("text") for page in document]
            except RuntimeError as exc:
                raise DocumentParserError("Failed to extract PDF text") from exc
            return ParsedDocument(
                text="\n".join(pages),
                page_count=document.page_count,
            )
