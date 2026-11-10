"""Vector store abstraction.

Each knowledge collection maps to its own *namespace* (a FAISS index file or a
Chroma collection). Physical separation per collection is a deliberate
security property: a query can only ever touch namespaces the caller has been
authorised for, so cross-tenant leakage via a mis-built metadata filter is
impossible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# where-filter format: {"document_id": ["a", "b"], "file_type": ["pdf"]}  (values OR-ed, keys AND-ed)
Where = dict[str, list[Any]]


@dataclass
class VectorHit:
    id: str
    score: float  # cosine similarity in [-1, 1]
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: np.ndarray | None = None


def matches(meta: dict[str, Any], where: Where | None) -> bool:
    if not where:
        return True
    return all(meta.get(k) in set(v) for k, v in where.items() if v)


def sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep scalar, non-null values only (portable across back-ends)."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


class VectorStore(ABC):
    name: str = "base"

    @abstractmethod
    def upsert(self, namespace: str, ids: list[str], vectors: np.ndarray, metadatas: list[dict[str, Any]]) -> None: ...

    @abstractmethod
    def delete(self, namespace: str, ids: list[str]) -> None: ...

    @abstractmethod
    def delete_namespace(self, namespace: str) -> None: ...

    @abstractmethod
    def search(self, namespace: str, query: np.ndarray, k: int, where: Where | None = None,
               include_vectors: bool = False) -> list[VectorHit]: ...

    @abstractmethod
    def get_vectors(self, namespace: str, ids: list[str]) -> dict[str, np.ndarray]: ...

    @abstractmethod
    def count(self, namespace: str) -> int: ...
