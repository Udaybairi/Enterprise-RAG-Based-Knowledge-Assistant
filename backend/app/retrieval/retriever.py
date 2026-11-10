"""Retrieval orchestrator.

Given one or more queries and the set of collections the *caller is
authorised for*, runs the configured strategy per collection namespace,
fuses results across queries, applies the similarity threshold, hydrates
chunk text from the DB (re-checking authorisation), de-duplicates
overlapping context and reranks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.config import get_settings
from app.core.logging import get_logger
from app.database.models import Document, DocumentStatus
from app.database.repositories import ChunkRepository
from app.database.session import session_scope
from app.ingestion.deduplication import dedupe_near
from app.llm.factory import get_llm
from app.retrieval.hybrid_search import weighted_rrf
from app.retrieval.keyword_index import keyword_index
from app.retrieval.reranker import Reranker
from app.retrieval.semantic_search import mmr_select, semantic_search
from app.retrieval.types import RetrievedChunk
from app.vectorstore.base import VectorStore
from app.vectorstore.factory import get_vector_store

log = get_logger(__name__)


@dataclass
class RetrievalConfig:
    strategy: str = "hybrid"
    top_k: int = 6
    fetch_k: int = 24
    similarity_threshold: float = 0.35
    mmr_lambda: float = 0.6
    hybrid_alpha: float = 0.6
    reranker: str = "lexical"
    document_ids: list[str] | None = None
    file_types: list[str] | None = None

    @classmethod
    def from_settings(cls, **overrides) -> "RetrievalConfig":
        s = get_settings()
        cfg = cls(strategy=s.retrieval_strategy, top_k=s.retrieval_top_k, fetch_k=s.retrieval_fetch_k,
                  similarity_threshold=s.similarity_threshold, mmr_lambda=s.mmr_lambda,
                  hybrid_alpha=s.hybrid_alpha, reranker=s.reranker)
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        cfg.fetch_k = max(cfg.fetch_k, cfg.top_k * 3)
        return cfg

    @property
    def where(self) -> dict | None:
        w = {}
        if self.document_ids:
            w["document_id"] = self.document_ids
        if self.file_types:
            w["file_type"] = [f.lstrip(".").lower() for f in self.file_types]
        return w or None


class Retriever:
    def __init__(self, store: VectorStore | None = None, embedder=None, llm=None, keyword_search=None,
                 hydrate=None):
        """``keyword_search`` / ``hydrate`` default to the DB-backed implementations; the evaluation
        harness injects in-memory equivalents to run against an isolated corpus."""
        from app.embeddings.factory import get_embedder

        self.store = store or get_vector_store()
        self.embedder = embedder or get_embedder()
        self.llm = llm
        self.keyword_search = keyword_search or keyword_index.search
        self.hydrate = hydrate or self._hydrate

    # ------------------------------------------------------------------ public
    def retrieve(self, queries: list[str], collection_ids: list[str], cfg: RetrievalConfig,
                 rerank_query: str | None = None) -> list[RetrievedChunk]:
        queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
        if not queries or not collection_ids:
            return []
        qvecs = self.embedder.embed_queries(queries)
        per_query: list[dict[str, RetrievedChunk]] = []
        for q, qv in zip(queries, qvecs):
            per_query.append(self._retrieve_one(q, qv, collection_ids, cfg))

        # Fuse across queries (multi-query retrieval) with RRF; the original query weighs most.
        rankings = []
        merged: dict[str, RetrievedChunk] = {}
        for i, res in enumerate(per_query):
            ordered = sorted(res.values(), key=lambda c: -c.score)
            rankings.append(([c.chunk_id for c in ordered], 1.0 if i == 0 else 0.7))
            for c in ordered:
                prev = merged.get(c.chunk_id)
                if prev is None or (c.vector_score or 0) > (prev.vector_score or 0):
                    merged[c.chunk_id] = c
        fused = weighted_rrf(rankings)
        for cid, c in merged.items():
            c.score = fused[cid]
        candidates = sorted(merged.values(), key=lambda c: -c.score)[: cfg.fetch_k]

        candidates = self.hydrate(candidates, collection_ids)
        candidates, removed = dedupe_near(candidates, key=lambda c: c.text, threshold=0.8)
        if removed:
            log.debug("context dedup removed %d overlapping chunks", removed)

        reranker = Reranker(cfg.reranker, llm=self.llm or (get_llm() if cfg.reranker == "llm" else None))
        ranked = reranker.rerank(rerank_query or queries[0], candidates, cfg.top_k)
        return ranked

    # ----------------------------------------------------------------- internals
    def _retrieve_one(self, query: str, qv: np.ndarray, collection_ids: list[str],
                      cfg: RetrievalConfig) -> dict[str, RetrievedChunk]:
        results: dict[str, RetrievedChunk] = {}
        where = cfg.where
        for ns in collection_ids:
            vec_hits = []
            if cfg.strategy in ("semantic", "hybrid", "mmr"):
                vec_hits = semantic_search(self.store, ns, qv, cfg.fetch_k, where,
                                           include_vectors=cfg.strategy == "mmr")
            kw_hits = []
            if cfg.strategy in ("hybrid", "keyword"):
                kw_hits = self.keyword_search(ns, query, cfg.fetch_k, where)

            chunks: dict[str, RetrievedChunk] = {}
            for h in vec_hits:
                chunks[h.id] = RetrievedChunk(
                    chunk_id=h.id, document_id=h.metadata.get("document_id", ""), collection_id=ns, text="",
                    vector_score=h.score, score=h.score, vector=h.vector,
                )
            kw_max = kw_hits[0][1] if kw_hits else 1.0
            for cid, s in kw_hits:
                c = chunks.get(cid) or RetrievedChunk(chunk_id=cid, document_id="", collection_id=ns, text="")
                c.keyword_score = s
                c.meta["keyword_norm"] = s / kw_max if kw_max else 0.0
                chunks[cid] = c

            # keyword-only hits get a real cosine score so the threshold applies uniformly
            missing = [cid for cid, c in chunks.items() if c.vector_score is None]
            if missing:
                vecs = self.store.get_vectors(ns, missing)
                for cid, v in vecs.items():
                    chunks[cid].vector_score = float(np.dot(v, qv) / max(np.linalg.norm(v) * np.linalg.norm(qv), 1e-12))

            chunks = {cid: c for cid, c in chunks.items() if self._passes_threshold(c, cfg)}

            if cfg.strategy == "mmr":
                items = [c for c in chunks.values() if c.vector is not None]
                order = mmr_select(qv, [c.vector for c in items], cfg.top_k * 2, cfg.mmr_lambda)
                for rank, idx in enumerate(order):
                    items[idx].score = 1.0 / (rank + 1)
                chunks = {items[i].chunk_id: items[i] for i in order}
            elif cfg.strategy == "hybrid":
                v_rank = [c.chunk_id for c in sorted(chunks.values(), key=lambda c: -(c.vector_score or -1))]
                k_rank = [c.chunk_id for c in sorted((c for c in chunks.values() if c.keyword_score),
                                                     key=lambda c: -(c.keyword_score or 0))]
                fused = weighted_rrf([(v_rank, cfg.hybrid_alpha), (k_rank, 1 - cfg.hybrid_alpha)])
                for cid, c in chunks.items():
                    c.score = fused.get(cid, 0.0)
            elif cfg.strategy == "keyword":
                for c in chunks.values():
                    c.score = c.keyword_score or 0.0
            results.update(chunks)
        return results

    @staticmethod
    def _passes_threshold(c: RetrievedChunk, cfg: RetrievalConfig) -> bool:
        cos = c.vector_score if c.vector_score is not None else -1.0
        if cos >= cfg.similarity_threshold:
            return True
        # strong exact keyword evidence (e.g. product codes, names) can rescue a lower cosine
        return (c.meta.get("keyword_norm", 0.0) >= 0.6) and cos >= cfg.similarity_threshold * 0.6

    def _hydrate(self, chunks: list[RetrievedChunk], allowed: list[str]) -> list[RetrievedChunk]:
        if not chunks:
            return []
        allowed_set = set(allowed)
        with session_scope() as db:
            rows = ChunkRepository(db).by_ids([c.chunk_id for c in chunks])
            doc_ids = {r.document_id for r in rows.values()}
            docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(doc_ids)).all()} if doc_ids else {}
            out = []
            for c in chunks:
                r = rows.get(c.chunk_id)
                d = docs.get(r.document_id) if r else None
                # Defence in depth: never return chunks outside the authorised collections
                if r is None or d is None or r.collection_id not in allowed_set \
                        or d.status != DocumentStatus.completed.value:
                    continue
                c.text = r.text
                c.document_id = r.document_id
                c.collection_id = r.collection_id
                c.page_number = r.page_number
                c.page_end = (r.meta or {}).get("page_end")
                c.section = r.section
                c.filename = d.filename
                c.file_type = d.file_type
                c.suspicious = bool((r.meta or {}).get("suspicious"))
                out.append(c)
        return out
