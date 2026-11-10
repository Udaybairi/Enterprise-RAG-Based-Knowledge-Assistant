"""Citation extraction and validation.

The model cites sources as ``[n]``. We map each marker to the exact chunk that
was in the context, strip markers that reference non-existent sources (never
fabricate), pick the most relevant snippet from each cited chunk and score
how well each cited sentence is supported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.context_builder import ContextSource
from app.rag.prompts import NOT_FOUND_MESSAGE
from app.utils.text import content_terms, split_sentences

_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


@dataclass
class CitationResult:
    answer: str
    citations: list[dict]
    grounded: bool
    is_refusal: bool
    invalid_markers: list[int] = field(default_factory=list)
    support_score: float = 0.0


def is_refusal(answer: str) -> bool:
    a = answer.strip().lower()
    return a.startswith(NOT_FOUND_MESSAGE[:60].lower()) or "couldn't find enough information" in a \
        or "could not find enough information" in a


def _best_snippet(text: str, evidence: str, max_len: int = 320) -> str:
    """Sentence(s) of the chunk that best support the citing answer sentences."""
    sents = split_sentences(text) or [text]
    ev = content_terms(evidence)
    best_i = max(range(len(sents)), key=lambda i: len(content_terms(sents[i]) & ev)) if ev else 0
    snippet = sents[best_i]
    j = best_i + 1
    while len(snippet) < 160 and j < len(sents):
        snippet += " " + sents[j]
        j += 1
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return snippet.strip()


def process_citations(answer: str, sources: list[ContextSource]) -> CitationResult:
    by_id = {s.id: s for s in sources}
    invalid: list[int] = []

    def _fix(m: re.Match) -> str:
        nums = [int(n) for n in re.split(r"\s*,\s*", m.group(1))]
        good = [n for n in nums if n in by_id]
        invalid.extend(n for n in nums if n not in by_id)
        return "".join(f"[{n}]" for n in good)

    cleaned = _MARKER_RE.sub(_fix, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned).strip()

    # evidence per source = answer sentences citing it
    evidence: dict[int, list[str]] = {}
    for sent in split_sentences(cleaned):
        for m in _MARKER_RE.finditer(sent):
            for n in re.split(r"\s*,\s*", m.group(1)):
                evidence.setdefault(int(n), []).append(_MARKER_RE.sub("", sent))

    order = []
    for m in _MARKER_RE.finditer(cleaned):
        for n in re.split(r"\s*,\s*", m.group(1)):
            if int(n) not in order:
                order.append(int(n))

    citations = []
    supported_sentences = 0
    total_sentences = 0
    for n in order:
        c = by_id[n].chunk
        ev = " ".join(evidence.get(n, []))
        for s in evidence.get(n, []):
            total_sentences += 1
            terms = content_terms(s)
            if terms and len(terms & content_terms(c.text)) / len(terms) >= 0.3:
                supported_sentences += 1
        citations.append({
            "index": n,
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "document_name": c.filename,
            "file_type": c.file_type,
            "collection_id": c.collection_id,
            "page_number": c.page_number,
            "page_end": c.page_end,
            "section": c.section,
            "snippet": _best_snippet(c.text, ev),
            "score": round(float(c.score), 4) if c.score is not None else None,
            "vector_score": round(float(c.vector_score), 4) if c.vector_score is not None else None,
        })
    refusal = is_refusal(cleaned)
    support = supported_sentences / total_sentences if total_sentences else 0.0
    return CitationResult(
        answer=cleaned,
        citations=[] if refusal else citations,
        grounded=bool(citations) and not refusal,
        is_refusal=refusal,
        invalid_markers=sorted(set(invalid)),
        support_score=round(support, 3),
    )
