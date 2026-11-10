"""The advanced RAG chain.

validate → rewrite (conversation-aware) → expand (multi-query) → retrieve
(semantic/hybrid/MMR + metadata filters) → dedupe → rerank → build context →
generate (Gemini, streaming) → validate citations → grounded answer.

``stream()`` yields events consumed by the SSE endpoint; ``run()`` collects
them for the JSON endpoint and the evaluation harness.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.llm.factory import get_llm
from app.rag.citation_manager import process_citations
from app.rag.context_builder import build_context
from app.rag.generator import AnswerGenerator
from app.rag.guardrails import redact_secrets
from app.rag.prompts import NOT_FOUND_MESSAGE
from app.rag.query_rewriter import QueryRewriter, format_history
from app.retrieval.retriever import RetrievalConfig, Retriever

log = get_logger(__name__)


@dataclass
class RAGResult:
    answer: str
    citations: list[dict]
    grounded: bool
    rewritten_query: str | None
    queries: list[str]
    latency_ms: float
    retrieval: dict[str, Any] = field(default_factory=dict)
    contexts: list[str] = field(default_factory=list)


class RAGChain:
    def __init__(self, llm: LLMClient | None = None, retriever: Retriever | None = None):
        self.llm = llm or get_llm()
        self.retriever = retriever or Retriever(llm=self.llm)
        self.rewriter = QueryRewriter(self.llm)
        self.generator = AnswerGenerator(self.llm)

    def stream(self, question: str, collection_ids: list[str], *, history: list[tuple[str, str]] | None = None,
               cfg: RetrievalConfig | None = None, rewrite: bool | None = None,
               multi_query: bool | None = None) -> Iterator[dict[str, Any]]:
        settings = get_settings()
        t0 = time.perf_counter()
        history = history or []
        cfg = cfg or RetrievalConfig.from_settings()
        rewrite = settings.enable_query_rewriting if rewrite is None else rewrite
        multi_query = (settings.multi_query_count > 0) if multi_query is None else multi_query

        yield {"type": "status", "stage": "query", "message": "Understanding the question"}
        plan = self.rewriter.plan(question, history, rewrite=rewrite, expand=multi_query,
                                  n_expansions=settings.multi_query_count)
        timings = {"query_ms": round((time.perf_counter() - t0) * 1000, 1)}

        yield {"type": "status", "stage": "retrieval", "message": "Searching the knowledge base",
               "queries": plan.queries}
        t1 = time.perf_counter()
        chunks = self.retriever.retrieve(plan.queries, collection_ids, cfg, rerank_query=plan.standalone)
        timings["retrieval_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        retrieval_info = {
            "strategy": cfg.strategy, "reranker": cfg.reranker, "top_k": cfg.top_k,
            "similarity_threshold": cfg.similarity_threshold, "retrieved": len(chunks),
            "queries": plan.queries, "timings": timings,
        }

        if not chunks:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            yield {"type": "token", "content": NOT_FOUND_MESSAGE}
            yield {"type": "final", "answer": NOT_FOUND_MESSAGE, "citations": [], "grounded": False,
                   "rewritten_query": plan.standalone if plan.rewritten else None, "latency_ms": latency,
                   "retrieval": retrieval_info, "contexts": []}
            return

        context, sources = build_context(chunks, settings.max_context_tokens)
        yield {"type": "status", "stage": "generation", "message": f"Reading {len(sources)} sources",
               "sources": len(sources)}
        t2 = time.perf_counter()
        hist_text = format_history(history, max_turns=4, max_chars=400) if history else ""
        parts: list[str] = []
        for delta in self.generator.stream(plan.standalone, context, hist_text):
            parts.append(delta)
            yield {"type": "token", "content": delta}
        timings["generation_ms"] = round((time.perf_counter() - t2) * 1000, 1)

        raw = redact_secrets("".join(parts).strip())
        result = process_citations(raw, sources)
        if result.invalid_markers:
            log.warning("Removed citations to non-existent sources: %s", result.invalid_markers)
        answer = result.answer
        if not result.grounded and not result.is_refusal:
            answer += ("\n\n> ⚠️ This answer did not cite the knowledge base and could not be verified. "
                       "Treat it with caution.")
        retrieval_info.update({"support_score": result.support_score, "invalid_citations": result.invalid_markers,
                               "used_sources": len(sources)})
        latency = round((time.perf_counter() - t0) * 1000, 1)
        yield {"type": "final", "answer": answer, "citations": result.citations, "grounded": result.grounded,
               "rewritten_query": plan.standalone if plan.rewritten else None, "latency_ms": latency,
               "retrieval": retrieval_info, "contexts": [s.chunk.text for s in sources],
               "context_chunk_ids": [s.chunk.chunk_id for s in sources]}

    def run(self, question: str, collection_ids: list[str], **kwargs) -> RAGResult:
        final: dict[str, Any] = {}
        for ev in self.stream(question, collection_ids, **kwargs):
            if ev["type"] == "final":
                final = ev
        return RAGResult(
            answer=final["answer"], citations=final["citations"], grounded=final["grounded"],
            rewritten_query=final.get("rewritten_query"), queries=final["retrieval"].get("queries", []),
            latency_ms=final["latency_ms"], retrieval=final["retrieval"], contexts=final.get("contexts", []),
        )
