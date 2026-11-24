"""Hybrid retrieval inside PostgreSQL: pgvector + full-text search in ONE round trip.

For every query variant (original, rewritten, expansions) and every authorised collection, a single
SQL statement:

* runs an HNSW nearest-neighbour search on ``rag_vectors`` (pgvector),
* runs a full-text search on ``chunks.search_tsv`` (generated ``tsvector`` + GIN index),
* joins chunk text, document metadata and the exact cosine similarity of every candidate,
* drops documents that are not ``completed``.

Fusion (reciprocal rank), thresholds, MMR and reranking stay in Python where they are testable.
This replaces the per-process in-memory BM25 index, which had to be rebuilt from every chunk in a
collection on each server instance.
"""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.retrieval.types import RetrievedChunk
from app.utils.text import STOPWORDS, tokenize

_SAFE_TERM = re.compile(r"^[a-z0-9]+$")


def tsquery_terms(query: str, max_terms: int = 24) -> str:
    """OR-query of content words for ``to_tsquery('english', ...)``.

    Natural-language questions are matched with OR semantics (like BM25); AND semantics
    (websearch_to_tsquery) returns nothing as soon as one question word is absent from a chunk.
    Terms are restricted to [a-z0-9] so user input can never produce tsquery syntax.
    """
    terms = []
    for t in tokenize(query):
        for part in t.replace("'", "-").split("-"):
            if part and part not in STOPWORDS and len(part) > 1 and _SAFE_TERM.match(part) and part not in terms:
                terms.append(part)
    return " | ".join(terms[:max_terms])


def _vec(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in np.asarray(v, dtype=np.float32).tolist()) + "]"


class PgHybridSearch:
    def __init__(self, engine: Engine, vector_table: str = "rag_vectors"):
        if not vector_table.replace("_", "").isalnum():
            raise ValueError("invalid table name")
        self.engine = engine
        self.vt = vector_table

    def search(self, queries: list[str], qvecs: np.ndarray, collection_ids: list[str], *, k: int,
               use_vector: bool = True, use_keyword: bool = True, where: dict[str, list] | None = None,
               include_vectors: bool = False) -> list[dict[str, RetrievedChunk]]:
        """Return one ``{chunk_id: RetrievedChunk}`` per query (same order as ``queries``)."""
        if not queries or not collection_ids:
            return [{} for _ in queries]
        where = where or {}
        params: dict[str, Any] = {
            "qis": list(range(len(queries))),
            "vecs": [_vec(v) for v in qvecs],
            "tqs": [tsquery_terms(q) for q in queries],
            "ns": list(collection_ids),
            "k": int(k) if use_vector else 0,
            "kk": int(k) if use_keyword else 0,
        }
        vfilter, kfilter = "", ""
        if where.get("document_id"):
            params["docs"] = [str(d) for d in where["document_id"]]
            vfilter += " AND r.metadata ->> 'document_id' = ANY(:docs)"
            kfilter += " AND c.document_id = ANY(:docs)"
        if where.get("file_type"):
            params["types"] = [str(t) for t in where["file_type"]]
            vfilter += " AND r.metadata ->> 'file_type' = ANY(:types)"
            kfilter += " AND d.file_type = ANY(:types)"
        emb = ", r.embedding::text AS emb" if include_vectors else ""
        sql = f"""
WITH qs AS (
    SELECT u.qi, u.v::vector AS v, u.t AS t
    FROM unnest(CAST(:qis AS int[]), CAST(:vecs AS text[]), CAST(:tqs AS text[])) AS u(qi, v, t)
),
vec AS (
    SELECT q.qi, x.id, row_number() OVER (PARTITION BY q.qi ORDER BY x.dist) AS rank_v
    FROM qs q CROSS JOIN LATERAL (
        SELECT r.id, r.embedding <=> q.v AS dist
        FROM {self.vt} r
        WHERE r.namespace = ANY(:ns){vfilter}
        ORDER BY r.embedding <=> q.v
        LIMIT :k
    ) x
),
kw AS (
    SELECT q.qi, y.id, y.ks, row_number() OVER (PARTITION BY q.qi ORDER BY y.ks DESC) AS rank_k
    FROM qs q CROSS JOIN LATERAL (
        SELECT c.id, ts_rank(c.search_tsv, to_tsquery('english', q.t), 1) AS ks
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE q.t <> '' AND c.collection_id = ANY(:ns) AND c.search_tsv @@ to_tsquery('english', q.t){kfilter}
        ORDER BY ks DESC
        LIMIT :kk
    ) y
),
cand AS (SELECT qi, id FROM vec UNION SELECT qi, id FROM kw)
SELECT cand.qi, c.id, c.document_id, c.collection_id, c.text, c.page_number, c.section, c.metadata,
       d.filename, d.file_type,
       1 - (r.embedding <=> q.v) AS cosine,
       vec.rank_v, kw.rank_k, kw.ks{emb}
FROM cand
JOIN qs q ON q.qi = cand.qi
JOIN chunks c ON c.id = cand.id
JOIN documents d ON d.id = c.document_id AND d.status = 'completed'
JOIN {self.vt} r ON r.namespace = c.collection_id AND r.id = c.id
LEFT JOIN vec ON vec.qi = cand.qi AND vec.id = cand.id
LEFT JOIN kw ON kw.qi = cand.qi AND kw.id = cand.id
"""
        with self.engine.begin() as conn:
            # keep scanning the HNSW index until enough rows pass the namespace/metadata filter
            conn.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            conn.execute(text("SET LOCAL hnsw.ef_search = 100"))
            rows = conn.execute(text(sql), params).mappings().all()

        out: list[dict[str, RetrievedChunk]] = [{} for _ in queries]
        for r in rows:
            meta = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"] or "{}")
            c = RetrievedChunk(
                chunk_id=r["id"], document_id=r["document_id"], collection_id=r["collection_id"], text=r["text"],
                filename=r["filename"], file_type=r["file_type"], page_number=r["page_number"],
                page_end=(meta or {}).get("page_end"), section=r["section"],
                vector_score=float(r["cosine"]), keyword_score=float(r["ks"]) if r["ks"] is not None else None,
                suspicious=bool((meta or {}).get("suspicious")),
                vector=np.array(json.loads(r["emb"]), dtype=np.float32) if include_vectors else None,
            )
            c.meta.update({"hydrated": True, "rank_v": r["rank_v"], "rank_k": r["rank_k"]})
            out[r["qi"]][c.chunk_id] = c
        return out
