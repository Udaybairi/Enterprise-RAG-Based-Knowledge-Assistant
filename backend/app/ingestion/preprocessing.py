"""Text cleaning and structure recovery.

* Unicode normalisation, de-hyphenation, whitespace normalisation.
* Repeated header/footer and page-number removal (paginated formats).
* Paragraph segmentation and heading detection for unstructured text (PDF/TXT).
* Section-path assignment (heading hierarchy) for every block.
* Duplicate paragraph removal.
* Empty / corrupted document detection.
* Prompt-injection flagging (content is kept but marked untrusted).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.core.exceptions import DocumentProcessingError
from app.ingestion.deduplication import dedupe_exact
from app.ingestion.types import Block, ExtractedDocument
from app.rag.guardrails import detect_injection
from app.utils.text import normalize_unicode

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​﻿]")
_PAGE_NUM_RE = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)
_NUMBERED_HEADING_RE = re.compile(r"^((\d+\.)+\d*|\d+\)|[IVXLC]+\.|[A-Z]\.)\s+[A-Z].{1,100}$")
_MIN_DOC_CHARS = 20


@dataclass
class PreprocessReport:
    removed_header_footer_lines: int = 0
    removed_duplicate_paragraphs: int = 0
    flagged_injection_blocks: int = 0
    detected_headings: int = 0
    warnings: list[str] = field(default_factory=list)


def clean_text(text: str) -> str:
    text = normalize_unicode(text)
    text = _CTRL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # de-hyphenate line breaks
    text = re.sub(r"[  ]{2,}", " ", text)            # collapse spaces
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)                # max one blank line
    return text.strip()


def _line_signature(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_headers_footers(pages: list[Block], report: PreprocessReport, edge_lines: int = 3) -> None:
    """Remove lines that repeat at the top/bottom of most pages (running headers/footers)."""
    if len(pages) < 3:
        for b in pages:
            lines = b.text.split("\n")
            kept = [l for i, l in enumerate(lines)
                    if not ((i < 2 or i >= len(lines) - 2) and _PAGE_NUM_RE.match(l))]
            report.removed_header_footer_lines += len(lines) - len(kept)
            b.text = "\n".join(kept)
        return
    counter: Counter[str] = Counter()
    for b in pages:
        lines = [l for l in b.text.split("\n") if l.strip()]
        edge = set(_line_signature(l) for l in lines[:edge_lines] + lines[-edge_lines:])
        counter.update(edge)
    threshold = max(3, math.ceil(len(pages) * 0.6))
    repeated = {sig for sig, n in counter.items() if n >= threshold and sig}
    for b in pages:
        lines = b.text.split("\n")
        non_empty_idx = [i for i, l in enumerate(lines) if l.strip()]
        edge_idx = set(non_empty_idx[:edge_lines] + non_empty_idx[-edge_lines:])
        kept = []
        for i, l in enumerate(lines):
            if i in edge_idx and (_line_signature(l) in repeated or _PAGE_NUM_RE.match(l)):
                report.removed_header_footer_lines += 1
                continue
            kept.append(l)
        b.text = "\n".join(kept)


def _looks_like_heading(line: str, next_line: str | None) -> int | None:
    """Heuristic heading detector for plain text (returns a heading level or None)."""
    s = line.strip()
    if not s or len(s) > 100 or len(s) < 3 or s.endswith((".", ",", ";", "?", "!")):
        return None
    words = s.split()
    if len(words) > 12:
        return None
    if re.match(r"^#{1,6}\s", s):
        return min(6, len(s) - len(s.lstrip("#")))
    if _NUMBERED_HEADING_RE.match(s):
        return min(4, s.split()[0].count(".") or 1)
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and len(words) <= 8:
        return 1
    if s.endswith(":") and len(words) <= 6 and s[0].isupper():
        return 3
    title_case = sum(1 for w in words if w[0].isupper() or not w[0].isalpha()) / len(words)
    if title_case >= 0.8 and len(words) <= 8 and not s.endswith(".") and next_line is not None \
            and len(next_line.strip()) > len(s):
        return 2
    return None


def segment_text_block(block: Block, report: PreprocessReport) -> list[Block]:
    """Split a page/text block into heading + paragraph blocks."""
    out: list[Block] = []
    paragraphs = re.split(r"\n\s*\n", block.text)
    for para in paragraphs:
        lines = [l for l in para.split("\n") if l.strip()]
        buf: list[str] = []
        for i, line in enumerate(lines):
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            level = _looks_like_heading(line, nxt) if (i == 0 or not buf or len(line) < 80) else None
            # Only treat as heading if it is a standalone line (start of paragraph or followed by text)
            if level is not None and (i == 0 or nxt is not None):
                if buf:
                    out.append(Block(" ".join(buf), "paragraph", block.page_number, list(block.section), meta=dict(block.meta)))
                    buf = []
                out.append(Block(line.strip().lstrip("#").strip().rstrip(":"), "heading", block.page_number,
                                 heading_level=level, meta=dict(block.meta)))
                report.detected_headings += 1
            else:
                buf.append(line.strip())
        if buf:
            text = "\n".join(buf) if _is_listy(buf) else " ".join(buf)
            kind = "list" if _is_listy(buf) else ("table" if buf[0].startswith("|") else "paragraph")
            if kind == "table":
                text = "\n".join(buf)
            out.append(Block(text, kind, block.page_number, list(block.section), meta=dict(block.meta)))
    return out


def _is_listy(lines: list[str]) -> bool:
    return sum(bool(re.match(r"^([-*•▪●]|\d+[.)])\s", l)) for l in lines) >= max(2, len(lines) // 2)


def assign_sections(blocks: list[Block]) -> list[Block]:
    """Propagate the heading hierarchy so every block knows its section path."""
    stack: list[tuple[int, str]] = []
    out = []
    for b in blocks:
        if b.kind == "heading":
            level = b.heading_level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, b.text.strip()[:200]))
            b.section = [t for _, t in stack]
        elif not b.section:
            b.section = [t for _, t in stack]
        elif stack and b.section and b.kind != "heading":
            # keep loader-provided section (e.g. sheet name) but nest it under document headings
            pass
        out.append(b)
    return out


def preprocess(doc: ExtractedDocument) -> tuple[ExtractedDocument, PreprocessReport]:
    report = PreprocessReport()
    for b in doc.blocks:
        b.text = clean_text(b.text) if b.kind not in ("table", "row") else normalize_unicode(_CTRL_RE.sub("", b.text)).strip()

    page_blocks = [b for b in doc.blocks if b.kind == "page"]
    if page_blocks:
        strip_headers_footers(page_blocks, report)

    blocks: list[Block] = []
    for b in doc.blocks:
        if b.kind in ("page", "text"):
            blocks.extend(segment_text_block(b, report))
        elif b.text.strip():
            blocks.append(b)

    blocks = [b for b in blocks if b.text.strip()]
    blocks, removed = dedupe_exact(blocks, key=lambda b: b.text if b.kind != "heading" else f"__h{id(b)}", min_len=40)
    report.removed_duplicate_paragraphs = removed
    blocks = assign_sections(blocks)

    for b in blocks:
        if b.kind != "heading" and detect_injection(b.text):
            b.meta["suspicious"] = True
            report.flagged_injection_blocks += 1

    body_chars = sum(len(b.text) for b in blocks if b.kind != "heading")
    if body_chars < _MIN_DOC_CHARS:
        raise DocumentProcessingError(
            "No extractable text found. The document may be empty, image-only (scanned), or corrupted."
        )
    if report.flagged_injection_blocks:
        report.warnings.append(
            f"{report.flagged_injection_blocks} block(s) contain instruction-like text and were marked untrusted"
        )
    doc.blocks = blocks
    return doc, report
