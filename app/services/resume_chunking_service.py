"""参照 SmartRecruit 实现简历父子分块。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResumeChunk:
    """子块用于检索，父块用于命中后补充完整语义上下文。"""

    chunk_id: str
    parent_id: str
    parent_index: int
    child_index: int
    text: str
    parent_content: str


class ResumeChunkingService:
    """按自然文本边界生成可追溯的父子块。"""

    def __init__(
        self,
        *,
        parent_chunk_size: int,
        child_chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        if child_chunk_size > parent_chunk_size:
            raise ValueError("child_chunk_size must not exceed parent_chunk_size")
        if chunk_overlap >= child_chunk_size:
            raise ValueError("chunk_overlap must be smaller than child_chunk_size")
        self._parent_chunk_size = parent_chunk_size
        self._child_chunk_size = child_chunk_size
        self._chunk_overlap = chunk_overlap

    def split(self, *, resume_id: int, text: str) -> list[ResumeChunk]:
        """先切父块，再切子块；每个子块保留所属父块全文。"""
        separators = ["\n\n", "\n", "。", "；", ";", " ", ""]
        chunks: list[ResumeChunk] = []
        parent_chunks = self._split_text(
            text,
            chunk_size=self._parent_chunk_size,
            overlap=self._chunk_overlap,
            separators=separators,
        )
        for parent_index, parent_content in enumerate(parent_chunks):
            parent_id = f"resume_{resume_id}_parent_{parent_index}"
            child_chunks = self._split_text(
                parent_content,
                chunk_size=self._child_chunk_size,
                overlap=self._chunk_overlap,
                separators=separators,
            )
            for child_index, child_text in enumerate(child_chunks):
                chunks.append(
                    ResumeChunk(
                        chunk_id=f"{parent_id}_child_{child_index}",
                        parent_id=parent_id,
                        parent_index=parent_index,
                        child_index=child_index,
                        text=child_text,
                        parent_content=parent_content,
                    )
                )
        return chunks

    @staticmethod
    def _split_text(
        text: str,
        *,
        chunk_size: int,
        overlap: int,
        separators: list[str],
    ) -> list[str]:
        """优先在段落、换行和句末切分，找不到边界时按字符切分。"""
        normalized = text.strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            hard_end = min(start + chunk_size, len(normalized))
            end = hard_end
            if hard_end < len(normalized):
                search_start = start + chunk_size // 2
                for separator in separators:
                    if not separator:
                        continue
                    boundary = normalized.rfind(separator, search_start, hard_end)
                    if boundary >= search_start:
                        end = boundary + len(separator)
                        break

            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - overlap, start + 1)
        return chunks
