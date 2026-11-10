"""Intermediate representations shared by loaders, preprocessing and chunkers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Block:
    """A structural unit of a document (heading, paragraph, table, list...)."""

    text: str
    kind: str = "paragraph"  # heading | paragraph | table | list | row
    page_number: int | None = None  # 1-based; None when the format has no pages (never invented)
    section: list[str] = field(default_factory=list)  # heading path, e.g. ["Policies", "Leave"]
    heading_level: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def section_title(self) -> str | None:
        return " > ".join(self.section) if self.section else None


@dataclass
class ExtractedDocument:
    blocks: list[Block]
    page_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    paginated: bool = True  # whether page numbers are real (PDF pages / PPTX slides)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


@dataclass
class ChunkData:
    text: str
    chunk_index: int = 0
    page_number: int | None = None
    page_end: int | None = None
    section: str | None = None
    token_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
