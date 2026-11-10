"""Google Gemini embeddings exposed through LangChain's ``Embeddings`` interface.

Features: batching, client-side rate limiting, exponential-backoff retries on
429/5xx, task-type aware embeddings (document vs. query), configurable output
dimensionality and L2 normalisation (so inner product == cosine similarity).
"""
from __future__ import annotations

import numpy as np
from langchain_core.embeddings import Embeddings

from app.config import Settings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.llm.retry import RequestRateLimiter, with_retries

log = get_logger(__name__)


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    if mat.ndim == 1:
        n = np.linalg.norm(mat)
        return mat / n if n > 0 else mat
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class GeminiEmbeddings(Embeddings):
    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        if not settings.google_api_key:
            raise ProviderError("GOOGLE_API_KEY is not configured", status_code=503)
        self._types = types
        self.model = settings.gemini_embedding_model
        self.dimension = settings.embedding_dimension
        self.batch_size = max(1, min(settings.embedding_batch_size, 100))  # API max 100 per request
        self.max_retries = settings.embedding_max_retries
        self.client = genai.Client(
            api_key=settings.google_api_key,
            http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
        )
        self._limiter = RequestRateLimiter(settings.embedding_requests_per_minute)
        self._supports_task_type = True
        self._supports_dimensionality = True

    @property
    def model_id(self) -> str:
        return f"{self.model}@{self.dimension}"

    def _config(self, task_type: str):
        kwargs = {}
        if self._supports_task_type:
            kwargs["task_type"] = task_type
        if self._supports_dimensionality:
            kwargs["output_dimensionality"] = self.dimension
        return self._types.EmbedContentConfig(**kwargs)

    def _embed_batch(self, texts: list[str], task_type: str) -> np.ndarray:
        def call():
            self._limiter.acquire()
            return self.client.models.embed_content(model=self.model, contents=texts, config=self._config(task_type))

        try:
            resp = with_retries(call, max_retries=self.max_retries, what=f"gemini embed ({len(texts)} texts)")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            # Newer embedding models may not accept every optional parameter;
            # degrade gracefully once rather than failing the whole ingestion.
            if getattr(exc, "code", None) == 400 and "task" in msg and self._supports_task_type:
                log.warning("Embedding model rejected task_type; retrying without it")
                self._supports_task_type = False
                return self._embed_batch(texts, task_type)
            if getattr(exc, "code", None) == 400 and "dimension" in msg and self._supports_dimensionality:
                log.warning("Embedding model rejected output_dimensionality; retrying without it")
                self._supports_dimensionality = False
                return self._embed_batch(texts, task_type)
            raise ProviderError(f"Gemini embedding failed: {exc}") from exc
        vectors = np.array([e.values for e in resp.embeddings], dtype=np.float32)
        if vectors.shape[0] != len(texts):
            raise ProviderError("Gemini returned an unexpected number of embeddings")
        if vectors.shape[1] != self.dimension:
            if vectors.shape[1] > self.dimension:  # Matryoshka truncation is valid for Gemini embeddings
                vectors = vectors[:, : self.dimension]
            else:
                raise ProviderError(
                    f"Embedding dimension {vectors.shape[1]} != configured EMBEDDING_DIMENSION {self.dimension}"
                )
        return l2_normalize(vectors)

    def embed_array(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        out = [self._embed_batch(texts[i:i + self.batch_size], task_type)
               for i in range(0, len(texts), self.batch_size)]
        return np.vstack(out)

    # LangChain interface -------------------------------------------------
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_array(texts, "RETRIEVAL_DOCUMENT").tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_array([text], "RETRIEVAL_QUERY")[0].tolist()
