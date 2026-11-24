"""Pick a usable Gemini model when the configured one is not available to this API key.

Google renames and retires models regularly, and which names resolve depends on the key and
API version. Instead of failing every request, the client lists the models the key can use
(``models.list``) and picks the best match for the role, preferring stable over preview
releases and newer over older ones.
"""
from __future__ import annotations

import re
import threading

from app.core.logging import get_logger

log = get_logger(__name__)

# Specialised variants that are not general text models.
_EXCLUDE = ("tts", "image", "audio", "live", "native", "computer-use", "robotics", "aqa", "learnlm",
            "gemma", "veo", "imagen", "lyria", "deep-research", "nano")
_PREFS = {
    "chat": [lambda n: "flash" in n and "lite" not in n, lambda n: "flash" in n, lambda n: "pro" in n],
    "utility": [lambda n: "flash-lite" in n, lambda n: "flash" in n and "lite" not in n, lambda n: "flash" in n],
    "embedding": [lambda n: "embedding" in n],
}
_ACTION = {"chat": "generateContent", "utility": "generateContent", "embedding": "embedContent"}


def _rank(name: str) -> tuple:
    stable = not any(t in name for t in ("preview", "exp"))
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    version = float(m.group(1)) if m else 0.0
    alias = name.endswith("-latest")
    return (stable, version, not alias, -len(name))


def candidates(available: dict[str, list[str]], wanted: str, role: str) -> list[str]:
    """Usable models for the role, best first (the configured model first if it is usable)."""
    action = _ACTION[role]
    usable = {n for n, actions in available.items() if action in (actions or [])}
    ordered: list[str] = [wanted] if wanted in usable else []
    if role != "embedding":
        usable = {n for n in usable if n.startswith("gemini") and not any(x in n for x in _EXCLUDE)}
    for pref in _PREFS[role]:
        for n in sorted((n for n in usable if pref(n)), key=_rank, reverse=True):
            if n not in ordered:
                ordered.append(n)
    return ordered


def choose_model(available: dict[str, list[str]], wanted: str, role: str) -> str | None:
    """``available`` maps model name (without ``models/``) to its supported actions."""
    ranked = candidates(available, wanted, role)
    return ranked[0] if ranked else None


class ModelResolver:
    """Process-wide cache of model listings and substitutions (one ``models.list`` call)."""

    def __init__(self) -> None:
        self._available: dict[str, list[str]] | None = None
        self._resolved: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def resolved(self, wanted: str, role: str) -> str:
        return self._resolved.get((wanted, role), wanted)

    def list_models(self, client) -> dict[str, list[str]]:
        with self._lock:
            if self._available is None:
                self._available = {(m.name or "").removeprefix("models/"): list(m.supported_actions or [])
                                   for m in client.models.list()}
            return self._available

    def alternatives(self, client, wanted: str, role: str, exclude: set[str]) -> list[str]:
        """Other usable models for the role, best first, for when one is overloaded or out of quota."""
        try:
            available = self.list_models(client)
        except Exception:  # noqa: BLE001
            return []
        return [m for m in candidates(available, wanted, role) if m not in exclude]

    def remember(self, wanted: str, role: str, model: str) -> None:
        if self._resolved.get((wanted, role)) != model:
            log.warning("Using Gemini model %r for %s (instead of %r).", model, role, self.resolved(wanted, role))
            with self._lock:
                self._resolved[(wanted, role)] = model

    def reset(self) -> None:
        with self._lock:
            self._available, self._resolved = None, {}


resolver = ModelResolver()


def is_model_not_found(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "")
    msg = str(exc).lower()
    return code == 404 or status == "NOT_FOUND" or (
        code == 400 and "not supported" in msg and ("model" in msg or "generatecontent" in msg))


def is_capacity_error(exc: Exception) -> bool:
    """Overloaded, unavailable or out of quota: another model may still work."""
    return getattr(exc, "code", None) in (429, 500, 503, 504)


def friendly_error(exc: Exception, what: str) -> str:
    """Short user-facing message; the full provider response is logged, not shown."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if code == 429:
        return f"{what} is rate-limited or out of quota right now. Please try again shortly."
    if code in (500, 503, 504):
        return f"{what} is temporarily overloaded at Google (HTTP {code}). Please try again in a minute."
    if code in (401, 403):
        return f"{what} rejected the API key (HTTP {code}). Check GOOGLE_API_KEY."
    if is_model_not_found(exc):
        return f"{what}: no suitable model is available for this API key. Check the GEMINI_* model settings."
    if code:
        return f"{what} failed (HTTP {code}{f' {status}' if status else ''}). Please try again."
    return f"{what} failed ({type(exc).__name__}). Please try again."
