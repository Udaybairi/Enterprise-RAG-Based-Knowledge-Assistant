"""PostgreSQL + pgvector vector store.

Stateless from the application's point of view, which makes it the right choice
for serverless deployments (Vercel + Neon/Supabase/any managed Postgres with
the ``vector`` extension). All collections share one table; the ``namespace``
column provides the same per-collection isolation as the Chroma/FAISS stores.

Schema (created on first use)::

    rag_vectors(namespace text, id text, embedding vector(<dim>), metadata jsonb,
                PRIMARY KEY (namespace, id))
    + btree index on namespace, HNSW index (cosine) on embedding

Queries always filter by namespace; pgvector >= 0.8 iterative index scans keep
filtered HNSW searches complete (``hnsw.iterative_scan``).
"""
from __future__ import annotations

import json
import threading
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.logging import get_logger
from app.vectorstore.base import VectorHit, VectorStore, Where, sanitize_metadata

log = get_logger(__name__)
TABLE = "rag_vectors"


def _vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in np.asarray(v, dtype=np.float32).tolist()) + "]"


def _parse_vec(s: str) -> np.ndarray:
    return np.array(json.loads(s), dtype=np.float32)


class PgVectorStore(VectorStore):
    name = "pgvector"

    def __init__(self, dimension: int, engine: Engine | None = None, table: str = TABLE):
        if not table.replace("_", "").isalnum():
            raise ValueError("invalid table name")
        self.table = table
        self.dim = dimension
        self._engine = engine
        self._ready = False
        self._lock = threading.Lock()

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            from app.database.session import get_engine

            self._engine = get_engine()
        return self._engine

    def _ensure_schema(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            if self.engine.dialect.name != "postgresql":
                raise RuntimeError("VECTOR_STORE=pgvector requires a PostgreSQL DATABASE_URL")
            with self.engine.begin() as conn:
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        "The pgvector extension is not available in this database. Enable it "
                        "(e.g. CREATE EXTENSION vector) or choose another VECTOR_STORE."
                    ) from exc
                conn.execute(text(
                    f"CREATE TABLE IF NOT EXISTS {self.table} ("
                    f" namespace text NOT NULL, id text NOT NULL, embedding vector({self.dim}) NOT NULL,"
                    f" metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb, PRIMARY KEY (namespace, id))"
                ))
                existing = conn.execute(text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    f"WHERE attrelid = '{self.table}'::regclass AND attname = 'embedding'"
                )).scalar()
                if existing != f"vector({self.dim})":
                    raise ValueError(
                        f"{self.table}.embedding is {existing}, but EMBEDDING_DIMENSION={self.dim}. "
                        "Re-create the table (and re-process documents) after changing the embedding model."
                    )
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {self.table}_namespace_idx ON {self.table} (namespace)"))
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_hnsw ON {self.table} "
                    "USING hnsw (embedding vector_cosine_ops)"
                ))
            self._ready = True

    # ---------------------------------------------------------------- operations
    def upsert(self, namespace, ids, vectors, metadatas) -> None:
        if not ids:
            return
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.shape != (len(ids), self.dim):
            raise ValueError(f"vectors shape {vectors.shape} != ({len(ids)}, {self.dim})")
        self._ensure_schema()
        rows = [{"ns": namespace, "id": i, "v": _vec_literal(v), "m": json.dumps(sanitize_metadata(m))}
                for i, v, m in zip(ids, vectors, metadatas)]
        stmt = text(
            f"INSERT INTO {self.table} (namespace, id, embedding, metadata) "
            "VALUES (:ns, :id, CAST(:v AS vector), CAST(:m AS jsonb)) "
            "ON CONFLICT (namespace, id) DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata"
        )
        with self.engine.begin() as conn:
            for start in range(0, len(rows), 500):
                conn.execute(stmt, rows[start:start + 500])

    def delete(self, namespace, ids) -> None:
        if not ids:
            return
        self._ensure_schema()
        with self.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {self.table} WHERE namespace = :ns AND id = ANY(:ids)"),
                         {"ns": namespace, "ids": list(ids)})

    def delete_namespace(self, namespace) -> None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {self.table} WHERE namespace = :ns"), {"ns": namespace})

    def search(self, namespace, query, k, where=None, include_vectors=False) -> list[VectorHit]:
        if k <= 0:
            return []
        self._ensure_schema()
        params: dict[str, Any] = {"ns": namespace, "q": _vec_literal(query), "k": int(k)}
        clauses = ["namespace = :ns"]
        for n, (key, values) in enumerate((where or {}).items()):
            if not values:
                continue
            params[f"key{n}"] = key
            params[f"val{n}"] = [str(v) for v in values]
            clauses.append(f"metadata ->> :key{n} = ANY(:val{n})")
        cols = "id, metadata, embedding <=> CAST(:q AS vector) AS distance"
        if include_vectors:
            cols += ", embedding::text AS emb"
        sql = (f"SELECT {cols} FROM {self.table} WHERE {' AND '.join(clauses)} "
               "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k")
        with self.engine.begin() as conn:
            # Keep scanning the HNSW index until enough rows pass the namespace/metadata filter
            # (pgvector >= 0.8; a harmless placeholder setting on older versions).
            conn.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            conn.execute(text("SET LOCAL hnsw.ef_search = 100"))
            rows = conn.execute(text(sql), params).mappings().all()
        hits = [VectorHit(r["id"], 1.0 - float(r["distance"]), dict(r["metadata"] or {}),
                          _parse_vec(r["emb"]) if include_vectors else None) for r in rows]
        hits.sort(key=lambda h: -h.score)  # relaxed_order may return slightly out-of-order rows
        return hits

    def get_vectors(self, namespace, ids) -> dict[str, np.ndarray]:
        if not ids:
            return {}
        self._ensure_schema()
        with self.engine.begin() as conn:
            rows = conn.execute(text(f"SELECT id, embedding::text AS emb FROM {self.table} "
                                     "WHERE namespace = :ns AND id = ANY(:ids)"),
                                {"ns": namespace, "ids": list(ids)}).all()
        return {r[0]: _parse_vec(r[1]) for r in rows}

    def count(self, namespace) -> int:
        self._ensure_schema()
        with self.engine.begin() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM {self.table} WHERE namespace = :ns"),
                                    {"ns": namespace}).scalar() or 0)
