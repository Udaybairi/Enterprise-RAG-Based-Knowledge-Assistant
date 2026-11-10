from __future__ import annotations

from app.chunking.base import Chunker
from app.chunking.recursive_chunker import RecursiveChunker
from app.chunking.semantic_chunker import SemanticChunker
from app.chunking.structure_chunker import StructureChunker
from app.chunking.token_chunker import TokenChunker
from app.config import get_settings

STRATEGIES = ("recursive", "token", "semantic", "structure")


def get_chunker(strategy: str | None = None, chunk_size: int | None = None, chunk_overlap: int | None = None,
                embedder=None) -> Chunker:
    s = get_settings()
    strategy = strategy or s.chunking_strategy
    size = chunk_size or s.chunk_size
    overlap = s.chunk_overlap if chunk_overlap is None else chunk_overlap
    if strategy == "recursive":
        return RecursiveChunker(size, overlap)
    if strategy == "token":
        return TokenChunker(size, overlap)
    if strategy == "structure":
        return StructureChunker(size, overlap)
    if strategy == "semantic":
        if embedder is None:
            from app.embeddings.factory import get_embedder

            embedder = get_embedder()
        return SemanticChunker(embedder.embed_uncached, size, 0, s.semantic_breakpoint_percentile,
                               s.semantic_buffer_size)
    raise ValueError(f"Unknown chunking strategy {strategy!r}; choose one of {STRATEGIES}")
