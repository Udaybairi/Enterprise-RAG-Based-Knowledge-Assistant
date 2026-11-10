"""In-memory numpy vector store (exact cosine). Used for the isolated evaluation index,
so evaluation works on every deployment target without FAISS or Chroma installed."""
from __future__ import annotations

import threading

import numpy as np

from app.vectorstore.base import VectorHit, VectorStore, matches, sanitize_metadata


class MemoryVectorStore(VectorStore):
    name = "memory"

    def __init__(self, dimension: int):
        self.dim = dimension
        self._ns: dict[str, dict[str, tuple[np.ndarray, dict]]] = {}
        self._lock = threading.Lock()

    def upsert(self, namespace, ids, vectors, metadatas) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(ids) and vectors.shape != (len(ids), self.dim):
            raise ValueError(f"vectors shape {vectors.shape} != ({len(ids)}, {self.dim})")
        with self._lock:
            ns = self._ns.setdefault(namespace, {})
            for i, v, m in zip(ids, vectors, metadatas):
                n = np.linalg.norm(v)
                ns[i] = (v / n if n else v, sanitize_metadata(m))

    def delete(self, namespace, ids) -> None:
        with self._lock:
            for i in ids:
                self._ns.get(namespace, {}).pop(i, None)

    def delete_namespace(self, namespace) -> None:
        with self._lock:
            self._ns.pop(namespace, None)

    def search(self, namespace, query, k, where=None, include_vectors=False) -> list[VectorHit]:
        with self._lock:
            items = [(i, v, m) for i, (v, m) in self._ns.get(namespace, {}).items() if matches(m, where)]
        if not items or k <= 0:
            return []
        q = np.asarray(query, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        scores = np.vstack([v for _, v, _ in items]) @ q
        order = np.argsort(-scores)[:k]
        return [VectorHit(items[j][0], float(scores[j]), dict(items[j][2]),
                          items[j][1] if include_vectors else None) for j in order]

    def get_vectors(self, namespace, ids) -> dict[str, np.ndarray]:
        ns = self._ns.get(namespace, {})
        return {i: ns[i][0] for i in ids if i in ns}

    def count(self, namespace) -> int:
        return len(self._ns.get(namespace, {}))
