"""Embedding cache: never pay twice for the same text.

Embeddings are keyed by ``sha256(text)`` + model id in the relational DB, which
makes re-processing, incremental updates and duplicate chunks across documents
free of API calls.
"""
from __future__ import annotations

import numpy as np

from app.core.logging import get_logger
from app.database.repositories import EmbeddingCacheRepository
from app.database.session import session_scope
from app.utils.text import sha256_text

log = get_logger(__name__)


class CachedEmbedder:
    def __init__(self, base):
        self.base = base

    @property
    def dimension(self) -> int:
        return self.base.dimension

    @property
    def model_id(self) -> str:
        return self.base.model_id

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        hashes = [sha256_text(t) for t in texts]
        with session_scope() as db:
            cached = EmbeddingCacheRepository(db).get_many(hashes, self.model_id)
        missing: dict[str, str] = {}
        for h, t in zip(hashes, texts):
            if h not in cached and h not in missing:
                missing[h] = t
        log.info("Embedding %d texts (%d cached, %d new)", len(texts), len(texts) - len(missing), len(missing))
        if missing:
            vecs = self.base.embed_array(list(missing.values()), "RETRIEVAL_DOCUMENT")
            fresh = dict(zip(missing.keys(), vecs))
            with session_scope() as db:
                EmbeddingCacheRepository(db).put_many(fresh, self.model_id)
            cached.update(fresh)
        return np.vstack([cached[h] for h in hashes]).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.base.embed_array([text], "RETRIEVAL_QUERY")[0]

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self.base.embed_array(texts, "RETRIEVAL_QUERY")

    def embed_uncached(self, texts: list[str], task_type: str = "SEMANTIC_SIMILARITY") -> np.ndarray:
        """Used for sentence-level embeddings (semantic chunking) that are not worth caching."""
        return self.base.embed_array(texts, task_type)
