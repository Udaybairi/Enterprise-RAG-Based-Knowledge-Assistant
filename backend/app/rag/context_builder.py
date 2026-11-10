"""Builds the numbered, token-budgeted context block passed to the LLM."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from app.rag.guardrails import neutralize_markup
from app.retrieval.types import RetrievedChunk
from app.utils.text import count_tokens, truncate_tokens


@dataclass
class ContextSource:
    id: int
    chunk: RetrievedChunk


def page_label(c: RetrievedChunk) -> str | None:
    if c.page_number is None:
        return None
    if c.page_end and c.page_end != c.page_number:
        return f"{c.page_number}-{c.page_end}"
    return str(c.page_number)


def build_context(chunks: list[RetrievedChunk], max_tokens: int = 12000) -> tuple[str, list[ContextSource]]:
    """Return (context string, sources). Chunks are assumed relevance-ordered; adjacent chunks of the
    same document are kept in reading order within the budget."""
    parts: list[str] = []
    sources: list[ContextSource] = []
    used = 0
    for c in chunks:
        attrs = [f'id="{len(sources) + 1}"', f'document="{escape(c.filename, quote=True)}"']
        page = page_label(c)
        if page:
            attrs.append(f'page="{page}"')
        if c.section:
            attrs.append(f'section="{escape(c.section[:200], quote=True)}"')
        if c.suspicious:
            attrs.append('untrusted="true"')
        body = neutralize_markup(c.text)
        overhead = count_tokens(" ".join(attrs)) + 10
        remaining = max_tokens - used - overhead
        if remaining <= 50:
            break
        if count_tokens(body) > remaining:
            body = truncate_tokens(body, remaining) + " …"
        block = f"<source {' '.join(attrs)}>\n{body}\n</source>"
        parts.append(block)
        sources.append(ContextSource(len(sources) + 1, c))
        used += count_tokens(block)
    return "\n\n".join(parts), sources
