from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.embeddings.cache import CachedEmbedder


@lru_cache
def get_embedder() -> CachedEmbedder:
    settings = get_settings()
    if settings.llm_provider == "fake":
        from app.embeddings.fake_embeddings import FakeEmbeddings

        base = FakeEmbeddings(settings.embedding_dimension)
    else:
        from app.embeddings.gemini_embeddings import GeminiEmbeddings

        base = GeminiEmbeddings(settings)
    return CachedEmbedder(base)
