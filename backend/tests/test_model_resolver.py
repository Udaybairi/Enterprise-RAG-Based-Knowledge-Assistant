"""The configured Gemini model may not exist for a given key / API version (seen in production:
'models/gemini-flash-latest is not found for API version v1'). Generation must recover."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.core.exceptions import ProviderError
from app.llm.model_resolver import choose_model, friendly_error, resolver

GEN, EMB = ["generateContent", "countTokens"], ["embedContent"]
AVAILABLE = {
    "gemini-2.5-flash": GEN, "gemini-2.5-flash-lite": GEN, "gemini-3-flash-preview": GEN,
    "gemini-3.1-flash": GEN, "gemini-3.1-flash-lite": GEN, "gemini-3.1-pro": GEN,
    "gemini-3.1-flash-image": GEN, "gemini-3.1-flash-tts": GEN, "gemma-4-27b": GEN,
    "gemini-embedding-001": EMB, "gemini-embedding-2": EMB,
}


def test_choose_model_prefers_newest_stable_for_role():
    assert choose_model(AVAILABLE, "gemini-flash-latest", "chat") == "gemini-3.1-flash"
    assert choose_model(AVAILABLE, "gemini-flash-lite-latest", "utility") == "gemini-3.1-flash-lite"
    assert choose_model(AVAILABLE, "gemini-2.5-flash", "chat") == "gemini-2.5-flash"  # configured one exists
    assert choose_model({"gemini-3-flash-preview": GEN}, "x", "chat") == "gemini-3-flash-preview"  # preview if only
    assert choose_model({"gemini-embedding-001": EMB}, "x", "chat") is None


def _not_found(model):
    return errors.APIError(404, {"error": {"code": 404, "status": "NOT_FOUND",
                                           "message": f"models/{model} is not found for API version v1"}})


class _FakeModels:
    def __init__(self, available):
        self.available = available
        self.calls: list[str] = []
        self.list_calls = 0

    def list(self):
        self.list_calls += 1
        return [SimpleNamespace(name=f"models/{n}", supported_actions=a) for n, a in self.available.items()]

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model not in self.available:
            raise _not_found(model)
        return SimpleNamespace(text=f"answer from {model}")

    def generate_content_stream(self, model, contents, config):
        self.calls.append(model)

        def gen():
            if model not in self.available:
                raise _not_found(model)  # raised lazily on first chunk, like the real SDK
            yield SimpleNamespace(text="Hello ")
            yield SimpleNamespace(text=f"from {model}")

        return gen()


@pytest.fixture
def llm():
    from app.llm.gemini_llm import GeminiLLM

    resolver.reset()
    g = GeminiLLM(Settings(google_api_key="k", gemini_chat_model="gemini-flash-latest",
                           gemini_utility_model="gemini-flash-lite-latest"))
    g.client = SimpleNamespace(models=_FakeModels(AVAILABLE))
    yield g
    resolver.reset()


def test_generate_falls_back_and_remembers(llm):
    assert llm.generate("q") == "answer from gemini-3.1-flash"
    assert llm.generate("q", utility=True) == "answer from gemini-3.1-flash-lite"
    llm.generate("again")
    m = llm.client.models
    assert m.list_calls == 1  # model list fetched once per process
    assert m.calls.count("gemini-flash-latest") == 1  # failing name not retried after resolution


def test_stream_falls_back_when_error_appears_on_first_chunk(llm):
    assert "".join(llm.stream("q")) == "Hello from gemini-3.1-flash"


def test_unrecoverable_error_is_readable(llm):
    llm.client.models.available = {"gemini-embedding-001": EMB}
    with pytest.raises(ProviderError) as e:
        "".join(llm.stream("q"))
    assert "no suitable model" in e.value.message and "{" not in e.value.message  # no raw JSON for users


def test_friendly_messages():
    assert "rate-limited" in friendly_error(errors.APIError(429, {"error": {"code": 429}}), "The AI model")
    assert "API key" in friendly_error(errors.APIError(403, {"error": {"code": 403}}), "The AI model")
