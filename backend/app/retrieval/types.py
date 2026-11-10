from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    collection_id: str
    text: str
    filename: str = ""
    file_type: str = ""
    page_number: int | None = None
    page_end: int | None = None
    section: str | None = None
    score: float = 0.0           # final score used for ordering
    vector_score: float | None = None  # cosine similarity
    keyword_score: float | None = None  # BM25
    rerank_score: float | None = None
    suspicious: bool = False
    vector: np.ndarray | None = field(default=None, repr=False)
    meta: dict[str, Any] = field(default_factory=dict)
