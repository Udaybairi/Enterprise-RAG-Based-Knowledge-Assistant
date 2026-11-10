"""Recursive character splitting (LangChain ``RecursiveCharacterTextSplitter``).

Runs page-by-page for paginated formats so every chunk carries an exact page
number, and maps chunk offsets back to blocks to recover section metadata.
"""
from __future__ import annotations

import bisect
from collections.abc import Callable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.chunking.base import Chunker
from app.ingestion.types import Block, ChunkData, ExtractedDocument

SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


class RecursiveChunker(Chunker):
    name = "recursive"

    def _splitter(self) -> RecursiveCharacterTextSplitter:
        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap,
            separators=SEPARATORS, add_start_index=True, keep_separator="end",
        )

    def _length_fn(self) -> Callable[[str], int]:
        return len

    def split(self, doc: ExtractedDocument) -> list[ChunkData]:
        splitter = self._splitter()
        groups: list[list[Block]] = []
        for b in doc.blocks:
            if doc.paginated and groups and groups[-1][-1].page_number == b.page_number:
                groups[-1].append(b)
            elif not doc.paginated and groups:
                groups[-1].append(b)
            else:
                groups.append([b])

        chunks: list[ChunkData] = []
        for blocks in groups:
            text, starts = "", []
            for b in blocks:
                if text:
                    text += "\n\n"
                starts.append(len(text))
                text += b.text
            for d in splitter.create_documents([text]):
                start = d.metadata.get("start_index", 0)
                if start < 0:
                    start = 0
                end = start + len(d.page_content)
                i0 = max(0, bisect.bisect_right(starts, start) - 1)
                i1 = max(0, bisect.bisect_right(starts, max(start, end - 1)) - 1)
                covered = blocks[i0:i1 + 1]
                pages = [b.page_number for b in covered if b.page_number is not None]
                meta = {"suspicious": True} if any(b.meta.get("suspicious") for b in covered) else {}
                # a heading inside the chunk defines its topic; otherwise the block where it starts
                section_block = next((b for b in covered if b.kind == "heading"), covered[0])
                chunks.append(ChunkData(
                    text=d.page_content.strip(),
                    page_number=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    section=section_block.section_title,
                    meta=meta,
                ))
        return chunks
