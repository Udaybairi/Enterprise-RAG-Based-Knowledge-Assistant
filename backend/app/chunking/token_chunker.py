"""Token-based chunking: recursive splitting measured in (approximate) LLM tokens."""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.chunking.recursive_chunker import SEPARATORS, RecursiveChunker
from app.utils.text import count_tokens


class TokenChunker(RecursiveChunker):
    """``chunk_size``/``chunk_overlap`` are given in characters for a uniform config
    surface and converted to tokens (~4 chars/token)."""

    name = "token"

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        super().__init__(chunk_size, chunk_overlap)
        self.token_size = max(32, chunk_size // 4)
        self.token_overlap = max(0, chunk_overlap // 4)

    def _splitter(self) -> RecursiveCharacterTextSplitter:
        return RecursiveCharacterTextSplitter(
            chunk_size=self.token_size, chunk_overlap=self.token_overlap, length_function=count_tokens,
            separators=SEPARATORS, add_start_index=True, keep_separator="end",
        )
