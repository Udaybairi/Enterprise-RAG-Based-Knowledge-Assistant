"""ChromaDB-backed persistent vector store."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from app.core.logging import get_logger
from app.vectorstore.base import VectorHit, VectorStore, Where, sanitize_metadata

log = get_logger(__name__)


def _to_chroma_where(where: Where | None):
    if not where:
        return None
    clauses = [{k: {"$in": list(v)}} for k, v in where.items() if v]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore(VectorStore):
    name = "chroma"

    def __init__(self, root: Path, dimension: int, client=None):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.dim = dimension
        path = Path(root) / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        self.client = client or chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False)
        )
        self._lock = threading.Lock()

    @staticmethod
    def _cname(namespace: str) -> str:
        return f"kb_{namespace}"

    def _col(self, namespace: str):
        with self._lock:
            return self.client.get_or_create_collection(
                name=self._cname(namespace), metadata={"hnsw:space": "cosine"}, embedding_function=None
            )

    def upsert(self, namespace, ids, vectors, metadatas) -> None:
        if not ids:
            return
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.shape != (len(ids), self.dim):
            raise ValueError(f"vectors shape {vectors.shape} != ({len(ids)}, {self.dim})")
        col = self._col(namespace)
        step = 2000
        for i in range(0, len(ids), step):
            col.upsert(
                ids=ids[i:i + step],
                embeddings=vectors[i:i + step].tolist(),
                metadatas=[sanitize_metadata(m) or {"_": 1} for m in metadatas[i:i + step]],
            )

    def delete(self, namespace, ids) -> None:
        if ids:
            self._col(namespace).delete(ids=list(ids))

    def delete_namespace(self, namespace) -> None:
        try:
            self.client.delete_collection(self._cname(namespace))
        except Exception:  # noqa: BLE001 - collection may not exist
            pass

    def search(self, namespace, query, k, where=None, include_vectors=False) -> list[VectorHit]:
        col = self._col(namespace)
        n = col.count()
        if n == 0 or k <= 0:
            return []
        include = ["metadatas", "distances"] + (["embeddings"] if include_vectors else [])
        res = col.query(
            query_embeddings=[np.asarray(query, dtype=np.float32).tolist()],
            n_results=min(k, n),
            where=_to_chroma_where(where),
            include=include,
        )
        hits = []
        embs = res.get("embeddings")
        for j, cid in enumerate(res["ids"][0]):
            vec = np.asarray(embs[0][j], dtype=np.float32) if include_vectors and embs is not None else None
            hits.append(VectorHit(cid, 1.0 - float(res["distances"][0][j]), dict(res["metadatas"][0][j] or {}), vec))
        return hits

    def get_vectors(self, namespace, ids) -> dict[str, np.ndarray]:
        if not ids:
            return {}
        res = self._col(namespace).get(ids=list(ids), include=["embeddings"])
        return {i: np.asarray(e, dtype=np.float32) for i, e in zip(res["ids"], res["embeddings"])}

    def count(self, namespace) -> int:
        return self._col(namespace).count()
