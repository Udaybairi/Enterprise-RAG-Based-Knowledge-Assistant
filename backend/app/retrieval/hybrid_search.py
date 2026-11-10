"""Hybrid retrieval: fuse dense and BM25 rankings with weighted Reciprocal Rank Fusion."""
from __future__ import annotations

from collections import defaultdict

RRF_K = 60


def weighted_rrf(rankings: list[tuple[list[str], float]], k: int = RRF_K) -> dict[str, float]:
    """``rankings`` is a list of (ordered ids, weight). Returns id → fused score."""
    fused: dict[str, float] = defaultdict(float)
    for ids, weight in rankings:
        for rank, cid in enumerate(ids):
            fused[cid] += weight / (k + rank + 1)
    return dict(fused)
