"""文档解析器公共抽象。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """文档解析器返回的原始结果。"""

    text: str
    page_count: int


class DocumentParserError(Exception):
    """文档无法正常解析。"""


class EncryptedDocumentError(DocumentParserError):
    """文档已加密，当前流程无法读取。"""


class DocumentLimitError(DocumentParserError):
    """文档超过允许的解析限制。"""


class BaseDocumentParser(ABC):
    """所有文档解析器需要实现的最小接口。"""

    @abstractmethod
    def parse(self, content: bytes) -> ParsedDocument:
        """从文档二进制内容中提取文本。"""
