"""Shared chunking primitives."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.ingestion.types import Block, ChunkData, ExtractedDocument
from app.utils.text import count_tokens, split_sentences


@dataclass
class Unit:
    """An atomic piece of text that should not be split further by the packer."""

    text: str
    page: int | None
    section: str | None
    kind: str = "paragraph"
    suspicious: bool = False
    meta: dict = field(default_factory=dict)


class Chunker(ABC):
    name = "base"

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @abstractmethod
    def split(self, doc: ExtractedDocument) -> list[ChunkData]: ...

    def chunk(self, doc: ExtractedDocument) -> list[ChunkData]:
        chunks = [c for c in self.split(doc) if c.text.strip()]
        for i, c in enumerate(chunks):
            c.chunk_index = i
            c.token_count = count_tokens(c.text)
            c.meta.setdefault("strategy", self.name)
        return chunks


def blocks_to_units(blocks: list[Block], max_chars: int) -> list[Unit]:
    """Convert blocks to units, splitting only blocks larger than ``max_chars`` (by sentence)."""
    units: list[Unit] = []
    for b in blocks:
        sec = b.section_title
        sus = bool(b.meta.get("suspicious"))
        if len(b.text) <= max_chars or b.kind == "heading":
            units.append(Unit(b.text, b.page_number, sec, b.kind, sus))
            continue
        if b.kind in ("table", "row"):
            # split tables on row boundaries, repeating the header row for context
            lines = b.text.split("\n")
            header = lines[:2] if len(lines) > 2 and lines[1].startswith("|-") else []
            body = lines[len(header):]
            buf: list[str] = []
            for line in body:
                if buf and len("\n".join(header + buf + [line])) > max_chars:
                    units.append(Unit("\n".join(header + buf), b.page_number, sec, b.kind, sus))
                    buf = []
                buf.append(line)
            if buf:
                units.append(Unit("\n".join(header + buf), b.page_number, sec, b.kind, sus))
            continue
        buf_s = ""
        for s in split_sentences(b.text):
            while len(s) > max_chars:  # pathological sentence without punctuation
                if buf_s:
                    units.append(Unit(buf_s, b.page_number, sec, "sentence", sus))
                    buf_s = ""
                units.append(Unit(s[:max_chars], b.page_number, sec, "sentence", sus))
                s = s[max_chars:]
            if buf_s and len(buf_s) + len(s) + 1 > max_chars:
                units.append(Unit(buf_s, b.page_number, sec, "sentence", sus))
                buf_s = ""
            buf_s = f"{buf_s} {s}".strip()
        if buf_s:
            units.append(Unit(buf_s, b.page_number, sec, "sentence", sus))
    return units


def make_chunk(units: list[Unit], section: str | None = None, **meta) -> ChunkData:
    pages = [u.page for u in units if u.page is not None]
    sep = lambda u: "\n" if u.kind in ("table", "row", "list") else "\n\n"  # noqa: E731
    text = ""
    for u in units:
        text = f"{text}{sep(u) if text else ''}{u.text}"
    m = dict(meta)
    if any(u.suspicious for u in units):
        m["suspicious"] = True
    kinds = sorted({u.kind for u in units})
    m["content_types"] = ",".join(kinds)
    return ChunkData(
        text=text.strip(),
        page_number=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        section=section if section is not None else next((u.section for u in units if u.section), None),
        meta=m,
    )


def overlap_tail(units: list[Unit], overlap_chars: int) -> list[Unit]:
    """Trailing units (whole units only) whose total length fits in ``overlap_chars``."""
    if overlap_chars <= 0:
        return []
    tail: list[Unit] = []
    total = 0
    for u in reversed(units):
        if u.kind == "heading":
            break
        if total + len(u.text) > overlap_chars:
            if not tail:  # use the last sentence(s) of the unit
                sents = split_sentences(u.text)
                picked = []
                for s in reversed(sents):
                    if total + len(s) > overlap_chars:
                        break
                    picked.insert(0, s)
                    total += len(s)
                if picked:
                    tail.append(Unit(" ".join(picked), u.page, u.section, "sentence", u.suspicious))
            break
        tail.insert(0, u)
        total += len(u.text)
    return tail


def group_by_section(units: list[Unit]) -> list[list[Unit]]:
    """Consecutive units sharing a section; a heading always starts a new group."""
    groups: list[list[Unit]] = []
    for u in units:
        prev = groups[-1][-1] if groups else None
        if prev is None or u.kind == "heading" or (u.section != prev.section and prev.kind != "heading"):
            groups.append([u])
        else:
            groups[-1].append(u)
    return groups


def merge_heading_only(groups: list[list[Unit]]) -> list[list[Unit]]:
    """Attach groups that consist solely of headings (e.g. a document title) to the next group."""
    out: list[list[Unit]] = []
    pending: list[Unit] = []
    for g in groups:
        if all(u.kind == "heading" for u in g):
            pending.extend(g)
            continue
        out.append(pending + g)
        pending = []
    if pending:
        out.append(pending)
    return out
