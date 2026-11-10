"""Semantic chunking driven by embedding similarity.

1. Respect structure: work inside section groups (never cross headings).
2. Units are whole paragraphs; only paragraphs larger than ``chunk_size`` are
   broken into sentences, so normal paragraphs are never split.
3. Each unit is embedded together with ``buffer_size`` neighbours (windowing
   smooths noise), and the cosine distance between consecutive windows is
   computed.
4. Boundaries are placed where the distance exceeds the document-level
   ``breakpoint_percentile``; sentence-level boundaries inside one paragraph
   are penalised to keep paragraphs together.
5. Hard size limits are enforced and very small chunks are merged.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from app.chunking.base import Chunker, Unit, blocks_to_units, group_by_section, make_chunk, merge_heading_only
from app.core.logging import get_logger
from app.ingestion.types import ChunkData, ExtractedDocument

log = get_logger(__name__)
EmbedFn = Callable[[list[str]], np.ndarray]
INTRA_PARAGRAPH_PENALTY = 0.8


class SemanticChunker(Chunker):
    name = "semantic"

    def __init__(self, embed_fn: EmbedFn, chunk_size: int = 1000, chunk_overlap: int = 0,
                 breakpoint_percentile: float = 90.0, buffer_size: int = 1):
        super().__init__(chunk_size, min(chunk_overlap, chunk_size - 1))
        self.embed_fn = embed_fn
        self.percentile = breakpoint_percentile
        self.buffer = buffer_size
        self.min_size = max(1, chunk_size // 5)

    def split(self, doc: ExtractedDocument) -> list[ChunkData]:
        units = blocks_to_units(doc.blocks, self.chunk_size)
        groups = merge_heading_only(group_by_section(units))

        # Collect windowed texts for every group that needs semantic splitting.
        windows: list[str] = []
        spans: list[tuple[int, int]] = []
        for g in groups:
            body = [u for u in g if u.kind != "heading"]
            if sum(len(u.text) for u in g) <= self.chunk_size or len(body) < 3:
                spans.append((-1, -1))
                continue
            start = len(windows)
            for i in range(len(g)):
                lo, hi = max(0, i - self.buffer), min(len(g), i + self.buffer + 1)
                windows.append(" ".join(x.text for x in g[lo:hi]))
            spans.append((start, len(windows)))

        distances_by_group: list[np.ndarray | None] = [None] * len(groups)
        if windows:
            emb = np.asarray(self.embed_fn(windows), dtype=np.float32)
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            emb = emb / np.where(norms == 0, 1, norms)
            all_d = []
            for gi, (s, e) in enumerate(spans):
                if s < 0:
                    continue
                e_ = emb[s:e]
                d = 1.0 - np.sum(e_[:-1] * e_[1:], axis=1)
                # penalise splitting between sentences of the same paragraph
                g = groups[gi]
                for i in range(len(d)):
                    if g[i].kind == "sentence" and g[i + 1].kind == "sentence":
                        d[i] *= INTRA_PARAGRAPH_PENALTY
                distances_by_group[gi] = d
                all_d.append(d)
            flat = np.concatenate(all_d) if all_d else np.array([])
            threshold = float(np.percentile(flat, self.percentile)) if flat.size else 1.0
        else:
            threshold = 1.0
        log.debug("semantic chunker threshold=%.4f over %d windows", threshold, len(windows))

        chunks: list[ChunkData] = []
        for g, d in zip(groups, distances_by_group):
            chunks.extend(self._split_group(g, d, threshold))
        return chunks

    def _split_group(self, g: list[Unit], d: np.ndarray | None, threshold: float) -> list[ChunkData]:
        section = next((u.section for u in g if u.kind != "heading" and u.section), g[0].section)
        if d is None:
            return [make_chunk(g, section)] if any(u.kind != "heading" for u in g) or len(g) else []
        heading = [g[0]] if g[0].kind == "heading" else []
        chunks: list[ChunkData] = []
        current: list[Unit] = []
        size = 0
        for i, u in enumerate(g):
            if current:
                semantic_break = d[i - 1] > threshold and size >= self.min_size
                size_break = size + len(u.text) + 2 > self.chunk_size
                if (semantic_break or size_break) and any(x.kind != "heading" for x in current):
                    chunks.append(make_chunk(current, section, boundary_distance=round(float(d[i - 1]), 4),
                                             boundary="semantic" if semantic_break and not size_break else "size"))
                    current = list(heading) if heading and u is not heading[0] else []
                    size = sum(len(x.text) + 2 for x in current)
            current.append(u)
            size += len(u.text) + 2
        if current and any(x.kind != "heading" for x in current):
            if chunks and size < self.min_size and len(chunks[-1].text) + size <= self.chunk_size:
                body = [x for x in current if x not in heading]
                merged = make_chunk([Unit(chunks[-1].text, chunks[-1].page_number, section)] + body, section)
                merged.page_end = max(filter(None, [chunks[-1].page_end, merged.page_end]), default=None)
                chunks[-1] = merged
            else:
                chunks.append(make_chunk(current, section))
        return chunks
