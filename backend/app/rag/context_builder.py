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
    # The exact passage text the model saw (may be a truncated prefix of chunk.text). Citations
    # and support checks use this, so they never point at text the model was not given.
    text: str = ""
    truncated: bool = False

    def __post_init__(self):
        if not self.text:
            self.text = self.chunk.text


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
        raw = c.text
        overhead = count_tokens(" ".join(attrs)) + 10
        remaining = max_tokens - used - overhead
        if remaining <= 50:
            break
        truncated = count_tokens(raw) > remaining
        if truncated:
            raw = truncate_tokens(raw, remaining)
        body = neutralize_markup(raw) + (" …" if truncated else "")
        block = f"<source {' '.join(attrs)}>\n{body}\n</source>"
        parts.append(block)
        sources.append(ContextSource(len(sources) + 1, c, text=raw, truncated=truncated))
        used += count_tokens(block)
    return "\n\n".join(parts), sources
