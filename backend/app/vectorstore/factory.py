from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.vectorstore.base import VectorStore


def build_vector_store(kind: str | None = None) -> VectorStore:
    settings = get_settings()
    kind = kind or settings.vector_store
    try:
        return _build(kind, settings)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"VECTOR_STORE={kind} needs the '{exc.name}' package. Install requirements-local.txt, "
            "or use VECTOR_STORE=pgvector (the slim/serverless install)."
        ) from exc


def _build(kind: str, settings) -> VectorStore:
    if kind == "faiss":
        from app.vectorstore.faiss_store import FaissVectorStore

        return FaissVectorStore(settings.vectors_dir, settings.embedding_dimension)
    if kind == "chroma":
        from app.vectorstore.chroma_store import ChromaVectorStore

        return ChromaVectorStore(settings.vectors_dir, settings.embedding_dimension)
    if kind == "pgvector":
        from app.vectorstore.pgvector_store import PgVectorStore

        return PgVectorStore(settings.embedding_dimension)
    raise ValueError(f"Unknown vector store {kind!r}")


@lru_cache
def get_vector_store() -> VectorStore:
    return build_vector_store()
