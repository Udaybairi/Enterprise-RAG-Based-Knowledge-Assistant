"""Google Gemini generation client (``google-genai`` SDK).

Resilience, in order of preference for each call:

1. the configured model (or the one this process last found working for the role);
2. ``GEMINI_FALLBACK_MODELS`` (explicit, each model has its own quota);
3. models discovered with ``models.list`` for the role (last resort).

A model is skipped when it is not found (404), overloaded (5xx) or out of quota (429). Transient
errors are retried with backoff first; exhausted daily quotas are not (waiting does not help).

Every call can append a trace record (purpose, model actually used, latency, tokens) so answers are
reproducible and per-question cost is measurable.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator

from app.config import Settings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.llm.model_resolver import friendly_error, is_capacity_error, is_model_not_found, resolver
from app.llm.retry import with_retries

log = get_logger(__name__)


def _usage(meta) -> dict:
    if meta is None:
        return {}
    return {"input_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
            "thinking_tokens": getattr(meta, "thoughts_token_count", None)}


class GeminiLLM(LLMClient):
    provider = "gemini"
    MAX_ALTERNATES = 3

    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        if not settings.google_api_key:
            raise ProviderError("GOOGLE_API_KEY is not configured", status_code=503)
        self._types = types
        self.settings = settings
        self.model = settings.gemini_chat_model
        self.utility_model = settings.gemini_utility_model or settings.gemini_chat_model
        self.client = genai.Client(
            api_key=settings.google_api_key,
            http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
        )
        self._no_thinking: set[str] = set()  # models that rejected thinking_config
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ config
    def _config(self, model, system, temperature, max_tokens, json_mode=False):
        kwargs = dict(
            system_instruction=system,
            temperature=self.settings.generation_temperature if temperature is None else temperature,
            max_output_tokens=max_tokens or self.settings.generation_max_output_tokens,
        )
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        level = self.settings.gemini_thinking_level
        if level and model not in self._no_thinking:
            kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_level=level)
        return self._types.GenerateContentConfig(**kwargs)

    def _thinking_rejected(self, exc: Exception, model: str) -> bool:
        if getattr(exc, "code", None) == 400 and "thinking" in str(exc).lower() and model not in self._no_thinking:
            with self._lock:
                self._no_thinking.add(model)
            log.info("Model %s does not accept thinking_config; sending requests without it", model)
            return True
        return False

    # ------------------------------------------------------------------ fallback
    def _candidates(self, role: str, wanted: str, tried: set[str]) -> list[str]:
        fallbacks = [m for m in self.settings.gemini_fallback_models if m and m not in tried]
        discovered = resolver.alternatives(self.client, wanted, role, tried | set(fallbacks))
        return fallbacks + discovered

    def _call(self, role: str, wanted: str, fn):
        """Run ``fn(model)``, moving through the fallback order on 404 / 429 / 5xx."""
        model = resolver.resolved(wanted, role)
        tried: set[str] = set()
        switches = 0
        while True:
            tried.add(model)
            try:
                try:
                    result = fn(model)
                except Exception as exc:  # noqa: BLE001
                    if self._thinking_rejected(exc, model):
                        result = fn(model)
                    else:
                        raise
                resolver.remember(wanted, role, model)
                return result, model
            except Exception as exc:  # noqa: BLE001
                if not (is_model_not_found(exc) or is_capacity_error(exc)) or switches >= self.MAX_ALTERNATES:
                    raise
                nxt = next(iter(self._candidates(role, wanted, tried)), None)
                if nxt is None:
                    raise
                switches += 1
                log.warning("Gemini model %r unusable (%s); trying %r", model,
                            getattr(exc, "code", type(exc).__name__), nxt)
                model = nxt

    # ------------------------------------------------------------------ API
    def generate(self, prompt, *, system=None, temperature=None, max_tokens=None, json_mode=False,
                 utility=False, trace=None, purpose="generate") -> str:
        role, wanted = ("utility", self.utility_model) if utility else ("chat", self.model)
        t0 = time.perf_counter()

        def call(model):
            cfg = self._config(model, system, temperature, max_tokens, json_mode)
            return with_retries(lambda: self.client.models.generate_content(model=model, contents=prompt, config=cfg),
                                max_retries=3, what=f"gemini generate ({model})")

        try:
            resp, model = self._call(role, wanted, call)
        except Exception as exc:  # noqa: BLE001
            log.exception("Gemini generation failed")
            if trace is not None:
                trace.append({"purpose": purpose, "model": None, "error": getattr(exc, "code", type(exc).__name__),
                              "ms": round((time.perf_counter() - t0) * 1000, 1)})
            raise ProviderError(friendly_error(exc, "The AI model")) from exc
        if trace is not None:
            trace.append({"purpose": purpose, "model": model, "ms": round((time.perf_counter() - t0) * 1000, 1),
                          **_usage(getattr(resp, "usage_metadata", None))})
        return resp.text or ""

    def stream(self, prompt, *, system=None, temperature=None, max_tokens=None, trace=None) -> Iterator[str]:
        t0 = time.perf_counter()

        def open_stream(model):
            cfg = self._config(model, system, temperature, max_tokens)

            # Errors (not found, 503 overloaded, 429 quota) surface when the first chunk is read, so
            # opening the stream AND reading the first chunk are retried together, inside the fallback.
            def attempt():
                it = iter(self.client.models.generate_content_stream(model=model, contents=prompt, config=cfg))
                return next(it, None), it

            return with_retries(attempt, max_retries=3, what=f"gemini stream ({model})")

        usage = None
        model = None
        first_token_ms = None
        try:
            (first, it), model = self._call("chat", self.model, open_stream)
            first_token_ms = round((time.perf_counter() - t0) * 1000, 1)
            if first is not None:
                usage = getattr(first, "usage_metadata", None) or usage
                if first.text:
                    yield first.text
            for chunk in it:
                usage = getattr(chunk, "usage_metadata", None) or usage
                if chunk.text:
                    yield chunk.text
        except Exception as exc:  # noqa: BLE001
            log.exception("Gemini streaming failed")
            if trace is not None:
                trace.append({"purpose": "answer", "model": model, "error": getattr(exc, "code", type(exc).__name__),
                              "ms": round((time.perf_counter() - t0) * 1000, 1)})
            raise ProviderError(friendly_error(exc, "The AI model")) from exc
        if trace is not None:
            trace.append({"purpose": "answer", "model": model, "ms": round((time.perf_counter() - t0) * 1000, 1),
                          "first_token_ms": first_token_ms, **_usage(usage)})
