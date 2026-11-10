"""Startup verification that the configured Gemini models are actually available."""
from __future__ import annotations

import threading
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
_status: dict[str, Any] = {"checked": False}
_lock = threading.Lock()


def check_models(force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    with _lock:
        if _status.get("checked") and not force:
            return dict(_status)
    if settings.llm_provider != "gemini":
        result = {"checked": True, "provider": settings.llm_provider, "ok": True,
                  "message": "Offline provider in use; Gemini models not checked."}
    elif not settings.google_api_key:
        result = {"checked": True, "provider": "gemini", "ok": False, "message": "GOOGLE_API_KEY is not set"}
    else:
        try:
            from google import genai

            client = genai.Client(api_key=settings.google_api_key)
            models = {}
            for m in client.models.list():
                name = (m.name or "").removeprefix("models/")
                models[name] = list(m.supported_actions or [])
            wanted = {
                "chat": (settings.gemini_chat_model, "generateContent"),
                "utility": (settings.gemini_utility_model, "generateContent"),
                "embedding": (settings.gemini_embedding_model, "embedContent"),
            }
            report = {}
            for role, (name, action) in wanted.items():
                actions = models.get(name)
                report[role] = {"model": name, "available": actions is not None,
                                "supports": action in (actions or []) if actions is not None else False}
            ok = all(r["available"] and r["supports"] for r in report.values())
            suggestions = sorted(n for n, a in models.items() if "embedContent" in a)[:10]
            result = {"checked": True, "provider": "gemini", "ok": ok, "models": report,
                      "available_embedding_models": suggestions,
                      "message": "All configured Gemini models are available" if ok else
                      "Some configured Gemini models are unavailable - update GEMINI_* settings"}
        except Exception as exc:  # noqa: BLE001
            result = {"checked": True, "provider": "gemini", "ok": False, "message": f"Model check failed: {exc}"}
    (log.info if result.get("ok") else log.warning)("Model check: %s", result.get("message"))
    with _lock:
        _status.clear()
        _status.update(result)
    return dict(result)


def model_status() -> dict[str, Any]:
    with _lock:
        return dict(_status)
