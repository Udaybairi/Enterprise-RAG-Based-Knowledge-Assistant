"""The advanced RAG chain.

validate → rewrite (conversation-aware) → expand (multi-query) → retrieve
(semantic/hybrid/MMR + metadata filters) → dedupe → rerank → build context →
generate (Gemini, streaming) → validate citations → grounded answer.

``stream()`` yields events consumed by the SSE endpoint; ``run()`` collects
them for the JSON endpoint and the evaluation harness.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.llm.factory import get_llm
from app.rag.citation_manager import process_citations
from app.rag.context_builder import build_context
from app.rag.generator import AnswerGenerator
from app.rag.guardrails import redact_secrets
from app.rag.prompts import NOT_FOUND_MESSAGE, PROMPT_VERSION
from app.rag.query_rewriter import QueryRewriter, format_history
from app.retrieval.retriever import RetrievalConfig, Retriever

log = get_logger(__name__)


def app_version() -> str:
    return (os.getenv("APP_VERSION") or os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("GIT_SHA") or "dev")[:12]


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
    provenance: dict[str, Any] = field(default_factory=dict)


class RAGChain:
    def __init__(self, llm: LLMClient | None = None, retriever: Retriever | None = None):
        self.llm = llm or get_llm()
        self.retriever = retriever or Retriever(llm=self.llm)
        self.rewriter = QueryRewriter(self.llm)
        self.generator = AnswerGenerator(self.llm)

    def stream(self, question: str, collection_ids: list[str], *, history: list[tuple[str, str]] | None = None,
               cfg: RetrievalConfig | None = None, rewrite: bool | None = None,
               multi_query: bool | None = None) -> Iterator[dict[str, Any]]:
        """``multi_query``: True = always expand, False = never, None = QUERY_EXPANSION setting."""
        settings = get_settings()
        t0 = time.perf_counter()
        history = history or []
        cfg = cfg or RetrievalConfig.from_settings()
        rewrite = settings.enable_query_rewriting if rewrite is None else rewrite
        expansion = settings.query_expansion if multi_query is None else ("always" if multi_query else "off")
        trace: list[dict] = []

        yield {"type": "status", "stage": "query", "message": "Understanding the question"}
        plan = self.rewriter.plan(question, history, rewrite=rewrite, expand=expansion == "always",
                                  n_expansions=settings.multi_query_count, trace=trace)
        timings = {"query_ms": round((time.perf_counter() - t0) * 1000, 1)}

        yield {"type": "status", "stage": "retrieval", "message": "Searching the knowledge base",
               "queries": plan.queries}
        t1 = time.perf_counter()
        chunks = self.retriever.retrieve(plan.queries, collection_ids, cfg, rerank_query=plan.standalone, trace=trace)
        expanded = expansion == "always"
        if expansion == "adaptive" and self._weak(chunks, cfg):
            # Only pay for query expansion when the direct query found little: saves a model call on
            # most questions (relevant for quotas and latency).
            extra = self.rewriter.expand(plan.standalone, settings.multi_query_count, trace)
            if extra:
                plan.queries = list(dict.fromkeys(plan.queries + extra))
                chunks = self.retriever.retrieve(plan.queries, collection_ids, cfg, rerank_query=plan.standalone,
                                                 trace=trace)
                expanded = True
        timings["retrieval_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        retrieval_info = {
            "strategy": cfg.strategy, "reranker": cfg.reranker, "top_k": cfg.top_k,
            "similarity_threshold": cfg.similarity_threshold, "retrieved": len(chunks),
            "queries": plan.queries, "expanded": expanded, "timings": timings,
        }

        if not chunks:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            yield {"type": "token", "content": NOT_FOUND_MESSAGE}
            yield {"type": "final", "answer": NOT_FOUND_MESSAGE, "citations": [], "grounded": False,
                   "rewritten_query": plan.standalone if plan.rewritten else None, "latency_ms": latency,
                   "retrieval": retrieval_info, "contexts": [],
                   "provenance": self._provenance(cfg, expansion, trace)}
            return

        context, sources = build_context(chunks, settings.max_context_tokens)
        yield {"type": "status", "stage": "generation", "message": f"Reading {len(sources)} sources",
               "sources": len(sources)}
        t2 = time.perf_counter()
        hist_text = format_history(history, max_turns=4, max_chars=400) if history else ""
        parts: list[str] = []
        for delta in self.generator.stream(plan.standalone, context, hist_text, trace=trace):
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
               "retrieval": retrieval_info, "contexts": [s.text for s in sources],
               "context_chunk_ids": [s.chunk.chunk_id for s in sources],
               "provenance": self._provenance(cfg, expansion, trace)}

    @staticmethod
    def _weak(chunks, cfg: RetrievalConfig) -> bool:
        """Expansion is worth a model call only if the direct query found nothing convincing. (A small
        result count alone is not a signal: a small knowledge base simply has few chunks.)"""
        if not chunks:
            return True
        best = max((c.vector_score or 0.0) for c in chunks)
        return best < cfg.similarity_threshold + 0.1

    def _provenance(self, cfg: RetrievalConfig, expansion: str, trace: list[dict]) -> dict[str, Any]:
        """Everything needed to reproduce or audit this answer."""
        settings = get_settings()
        answer_call = next((t for t in reversed(trace) if t.get("purpose") == "answer"), {})
        tokens = {k: sum((t.get(k) or 0) for t in trace) for k in ("input_tokens", "output_tokens", "thinking_tokens")}
        return {
            "app_version": app_version(),
            "prompt_version": PROMPT_VERSION,
            "provider": self.llm.provider,
            "answer_model": answer_call.get("model"),
            "models_used": sorted({t["model"] for t in trace if t.get("model")}),
            "embedding_model": getattr(self.retriever.embedder, "model_id", None),
            "retrieval_config": {k: v for k, v in asdict(cfg).items() if k not in ("document_ids", "file_types")},
            "query_expansion": expansion,
            "model_calls": len(trace),
            "tokens": tokens,
            "calls": trace,
        }

    def run(self, question: str, collection_ids: list[str], **kwargs) -> RAGResult:
        final: dict[str, Any] = {}
        for ev in self.stream(question, collection_ids, **kwargs):
            if ev["type"] == "final":
                final = ev
        return RAGResult(
            answer=final["answer"], citations=final["citations"], grounded=final["grounded"],
            rewritten_query=final.get("rewritten_query"), queries=final["retrieval"].get("queries", []),
            latency_ms=final["latency_ms"], retrieval=final["retrieval"], contexts=final.get("contexts", []),
            provenance=final.get("provenance", {}),
        )
