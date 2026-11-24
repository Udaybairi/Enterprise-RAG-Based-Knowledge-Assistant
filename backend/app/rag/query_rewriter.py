"""Query processing: validation, conversational rewriting and multi-query expansion."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.rag.guardrails import neutralize_markup, validate_query
from app.rag.prompts import expand_prompt, rewrite_prompt

log = get_logger(__name__)


@dataclass
class QueryPlan:
    original: str
    standalone: str
    queries: list[str] = field(default_factory=list)
    rewritten: bool = False


def format_history(history: list[tuple[str, str]], max_turns: int = 6, max_chars: int = 600) -> str:
    lines = []
    for role, content in history[-max_turns:]:
        content = content.strip().replace("\n", " ")
        if len(content) > max_chars:
            content = content[:max_chars] + "…"
        lines.append(f"{'User' if role == 'user' else 'Assistant'}: {neutralize_markup(content)}")
    return "\n".join(lines)


class QueryRewriter:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def expand(self, question: str, n: int, trace: list[dict] | None = None) -> list[str]:
        """Alternative phrasings of the question (multi-query retrieval)."""
        if n <= 0:
            return []
        try:
            data = self.llm.generate_json(expand_prompt(neutralize_markup(question), n), trace=trace,
                                          purpose="query_expansion")
            return [q.strip() for q in data.get("queries", [])[:n] if isinstance(q, str) and q.strip() and len(q) < 500]
        except Exception as exc:  # noqa: BLE001
            log.warning("query expansion failed: %s", exc)
            return []

    def plan(self, question: str, history: list[tuple[str, str]], *, rewrite: bool = True,
             expand: bool = True, n_expansions: int = 3, trace: list[dict] | None = None) -> QueryPlan:
        question = validate_query(question)
        standalone = question
        rewritten = False
        if rewrite and history:
            try:
                data = self.llm.generate_json(rewrite_prompt(neutralize_markup(question), format_history(history)),
                                              trace=trace, purpose="query_rewrite")
                candidate = str(data.get("standalone_question", "")).strip()
                if candidate and len(candidate) < 1000:
                    rewritten = candidate.lower() != question.lower()
                    standalone = candidate
            except Exception as exc:  # noqa: BLE001
                log.warning("query rewrite failed: %s", exc)
        queries = [standalone]
        if rewritten:
            queries.append(question)
        if expand:
            queries.extend(self.expand(standalone, n_expansions, trace))
        queries = list(dict.fromkeys(queries))
        return QueryPlan(original=question, standalone=standalone, queries=queries, rewritten=rewritten)
