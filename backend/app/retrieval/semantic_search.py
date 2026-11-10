"""Dense (vector) retrieval and Maximal Marginal Relevance."""
from __future__ import annotations

import numpy as np

from app.vectorstore.base import VectorHit, VectorStore, Where


def semantic_search(store: VectorStore, namespace: str, query_vec: np.ndarray, k: int,
                    where: Where | None = None, include_vectors: bool = False) -> list[VectorHit]:
    return store.search(namespace, query_vec, k, where=where, include_vectors=include_vectors)


def mmr_select(query_vec: np.ndarray, candidates: list[np.ndarray], k: int, lambda_mult: float = 0.6) -> list[int]:
    """Maximal Marginal Relevance: balance relevance to the query with diversity.

    Returns indices into ``candidates`` in selection order.
    """
    if not candidates:
        return []
    mat = np.vstack(candidates).astype(np.float32)
    mat /= np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)
    q = np.asarray(query_vec, dtype=np.float32)
    q /= max(np.linalg.norm(q), 1e-12)
    rel = mat @ q
    sim = mat @ mat.T
    selected: list[int] = [int(np.argmax(rel))]
    remaining = set(range(len(candidates))) - set(selected)
    while remaining and len(selected) < k:
        rem = np.array(sorted(remaining))
        redundancy = sim[np.ix_(rem, selected)].max(axis=1)
        scores = lambda_mult * rel[rem] - (1 - lambda_mult) * redundancy
        best = int(rem[int(np.argmax(scores))])
        selected.append(best)
        remaining.discard(best)
    return selected
