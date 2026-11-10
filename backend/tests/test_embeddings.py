from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.config import Settings
from app.embeddings.cache import CachedEmbedder
from app.embeddings.fake_embeddings import FakeEmbeddings
from app.llm import retry


class _CountingEmbeddings(FakeEmbeddings):
    def __init__(self):
        super().__init__(32)
        self.embedded: list[str] = []

    def embed_array(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.embedded.extend(texts)
        return super().embed_array(texts, task_type)


def test_cache_prevents_duplicate_embedding(client):  # client fixture initialises the DB
    base = _CountingEmbeddings()
    emb = CachedEmbedder(base)
    a = emb.embed_documents(["alpha text", "beta text", "alpha text"])
    assert base.embedded == ["alpha text", "beta text"]  # duplicate within batch embedded once
    b = emb.embed_documents(["beta text", "gamma text"])
    assert base.embedded[-1:] == ["gamma text"]  # beta came from cache
    assert np.allclose(a[1], b[0])


class _APIError(Exception):
    def __init__(self, code, message="error"):
        super().__init__(f"{code} {message}")
        self.code = code


def test_retry_on_rate_limit(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _APIError(429)
        return "ok"

    assert retry.with_retries(flaky, max_retries=5) == "ok" and calls["n"] == 3


def test_no_retry_on_client_error(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise _APIError(400)

    with pytest.raises(_APIError):
        retry.with_retries(bad, max_retries=5)
    assert calls["n"] == 1


class _FakeModels:
    def __init__(self, reject_task_type=False):
        self.calls = []
        self.reject = reject_task_type

    def embed_content(self, model, contents, config):
        self.calls.append((len(contents), config.task_type))
        if self.reject and config.task_type is not None:
            raise _APIError(400, "task_type is not supported by this model")
        return SimpleNamespace(embeddings=[SimpleNamespace(values=list(np.arange(1, 9, dtype=float)))
                                           for _ in contents])


def _gemini(reject=False):
    from app.embeddings.gemini_embeddings import GeminiEmbeddings

    s = Settings(google_api_key="test-key", embedding_dimension=8, embedding_batch_size=3,
                 embedding_requests_per_minute=100000)
    g = GeminiEmbeddings(s)
    g.client = SimpleNamespace(models=_FakeModels(reject))
    return g


def test_gemini_embeddings_batching_and_normalisation():
    g = _gemini()
    out = g.embed_array([f"t{i}" for i in range(7)])
    assert out.shape == (7, 8)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)
    assert [c[0] for c in g.client.models.calls] == [3, 3, 1]
    g.embed_query("q")
    assert g.client.models.calls[-1][1] == "RETRIEVAL_QUERY"


def test_gemini_embeddings_task_type_fallback():
    g = _gemini(reject=True)
    out = g.embed_array(["a", "b"])
    assert out.shape == (2, 8) and g._supports_task_type is False


class _FakeGenModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(("generate", model, config))
        return SimpleNamespace(text='{"standalone_question": "q"}')

    def generate_content_stream(self, model, contents, config):
        self.calls.append(("stream", model, config))
        return iter([SimpleNamespace(text="Hello "), SimpleNamespace(text=None), SimpleNamespace(text="world [1].")])


def test_gemini_llm_generate_stream_and_models():
    from app.llm.gemini_llm import GeminiLLM

    s = Settings(google_api_key="test-key", gemini_chat_model="chat-m", gemini_utility_model="util-m")
    llm = GeminiLLM(s)
    llm.client = SimpleNamespace(models=_FakeGenModels())
    assert llm.generate_json("<task>rewrite</task>") == {"standalone_question": "q"}
    kind, model, cfg = llm.client.models.calls[-1]
    assert model == "util-m" and cfg.response_mime_type == "application/json" and cfg.temperature == 0.0
    assert "".join(llm.stream("prompt", system="sys")) == "Hello world [1]."
    kind, model, cfg = llm.client.models.calls[-1]
    assert kind == "stream" and model == "chat-m" and cfg.system_instruction == "sys"


def test_gemini_requires_key():
    from app.core.exceptions import ProviderError
    from app.llm.gemini_llm import GeminiLLM

    with pytest.raises(ProviderError):
        GeminiLLM(Settings(google_api_key=None))
