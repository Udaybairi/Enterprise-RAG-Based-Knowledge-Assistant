"""Deterministic offline embeddings (feature hashing) for tests / key-less runs.

Uses hashed stemmed unigrams, bigrams and character trigrams, so lexically and
morphologically related texts land close together. Not a substitute for
Gemini quality, but it lets every pipeline stage run reproducibly offline.
"""
from __future__ import annotations

import hashlib

import numpy as np
from langchain_core.embeddings import Embeddings

from app.embeddings.gemini_embeddings import l2_normalize
from app.utils.text import keyword_tokens


def _h(s: str, dim: int) -> tuple[int, float]:
    d = hashlib.blake2b(s.encode(), digest_size=8).digest()
    v = int.from_bytes(d, "little")
    return v % dim, (1.0 if (v >> 63) & 1 else -1.0)


class FakeEmbeddings(Embeddings):
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.model = "fake-hash-embedding"

    @property
    def model_id(self) -> str:
        return f"{self.model}@{self.dimension}"

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        toks = keyword_tokens(text)
        for t in toks:
            i, s = _h("u:" + t, self.dimension)
            vec[i] += 2.0 * s
            padded = f"#{t}#"
            for k in range(len(padded) - 2):
                i, s = _h("c:" + padded[k:k + 3], self.dimension)
                vec[i] += 0.3 * s
        for a, b in zip(toks, toks[1:]):
            i, s = _h(f"b:{a}_{b}", self.dimension)
            vec[i] += 1.0 * s
        return vec

    def embed_array(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return l2_normalize(np.vstack([self._one(t) for t in texts]))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_array(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_array([text], "RETRIEVAL_QUERY")[0].tolist()
