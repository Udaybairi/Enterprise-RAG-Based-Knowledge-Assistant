"""Google Gemini generation client (``google-genai`` SDK)."""
from __future__ import annotations

from collections.abc import Iterator

from app.config import Settings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.llm.model_resolver import friendly_error, is_capacity_error, is_model_not_found, resolver
from app.llm.retry import with_retries

log = get_logger(__name__)


class GeminiLLM(LLMClient):
    provider = "gemini"

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

    def _config(self, system, temperature, max_tokens, json_mode=False):
        kwargs = dict(
            system_instruction=system,
            temperature=self.settings.generation_temperature if temperature is None else temperature,
            max_output_tokens=max_tokens or self.settings.generation_max_output_tokens,
        )
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        return self._types.GenerateContentConfig(**kwargs)

    MAX_ALTERNATES = 2

    def _call(self, role: str, wanted: str, fn):
        """Run ``fn(model)`` with graceful degradation:

        * model not found for this key  -> switch to the best available model for the role;
        * overloaded / out of quota after retries -> try up to MAX_ALTERNATES other models.
        A model that works is remembered for this process.
        """
        model = resolver.resolved(wanted, role)
        tried: set[str] = set()
        alternates_left = self.MAX_ALTERNATES
        while True:
            tried.add(model)
            try:
                result = fn(model)
                resolver.remember(wanted, role, model)
                return result
            except Exception as exc:  # noqa: BLE001
                if is_model_not_found(exc):
                    nxt = next(iter(resolver.alternatives(self.client, wanted, role, tried)), None)
                elif is_capacity_error(exc) and alternates_left > 0:
                    alternates_left -= 1
                    nxt = next(iter(resolver.alternatives(self.client, wanted, role, tried)), None)
                    if nxt:
                        log.warning("Gemini model %r unavailable (%s); trying %r", model,
                                    getattr(exc, "code", type(exc).__name__), nxt)
                else:
                    nxt = None
                if nxt is None:
                    raise
                model = nxt

    def generate(self, prompt, *, system=None, temperature=None, max_tokens=None, json_mode=False,
                 utility=False) -> str:
        role, wanted = ("utility", self.utility_model) if utility else ("chat", self.model)
        cfg = self._config(system, temperature, max_tokens, json_mode)

        def call(model):
            return with_retries(lambda: self.client.models.generate_content(model=model, contents=prompt, config=cfg),
                                max_retries=4, what=f"gemini generate ({model})")

        try:
            resp = self._call(role, wanted, call)
        except Exception as exc:  # noqa: BLE001
            log.exception("Gemini generation failed")
            raise ProviderError(friendly_error(exc, "The AI model")) from exc
        return resp.text or ""

    def stream(self, prompt, *, system=None, temperature=None, max_tokens=None) -> Iterator[str]:
        cfg = self._config(system, temperature, max_tokens)

        def open_stream(model):
            # Errors (not found, 503 overloaded, 429 quota) surface when the first chunk is read, so
            # opening the stream AND reading the first chunk are retried together, inside the fallback.
            def attempt():
                it = iter(self.client.models.generate_content_stream(model=model, contents=prompt, config=cfg))
                return next(it, None), it

            return with_retries(attempt, max_retries=3, what=f"gemini stream ({model})")

        try:
            first, it = self._call("chat", self.model, open_stream)
            if first is not None and first.text:
                yield first.text
            for chunk in it:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:  # noqa: BLE001
            log.exception("Gemini streaming failed")
            raise ProviderError(friendly_error(exc, "The AI model")) from exc
