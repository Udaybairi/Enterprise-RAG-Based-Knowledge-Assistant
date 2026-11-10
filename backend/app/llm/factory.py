from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMClient


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "fake":
        from app.llm.fake_llm import FakeLLM

        return FakeLLM()
    from app.llm.gemini_llm import GeminiLLM

    return GeminiLLM(settings)
