"""Retry / rate-limit helpers for Gemini API calls."""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from app.core.logging import get_logger

T = TypeVar("T")
log = get_logger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _status_of(exc: Exception) -> int | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def is_retryable(exc: Exception) -> bool:
    status = _status_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    # network-level failures (timeouts, resets) are worth retrying
    name = type(exc).__name__.lower()
    return any(k in name for k in ("timeout", "connect", "network", "remoteprotocol", "readerror"))


def with_retries(fn: Callable[[], T], *, max_retries: int = 5, base_delay: float = 1.0,
                 max_delay: float = 60.0, what: str = "request") -> T:
    """Run ``fn`` with exponential backoff + full jitter on retryable errors."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if attempt >= max_retries or not is_retryable(exc):
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            # honour 429 more conservatively
            if _status_of(exc) == 429:
                delay = max(delay, 5.0)
            delay = random.uniform(delay / 2, delay)
            attempt += 1
            log.warning("%s failed (%s: %s); retry %d/%d in %.1fs", what, type(exc).__name__,
                        str(exc)[:200], attempt, max_retries, delay)
            time.sleep(delay)


class RequestRateLimiter:
    """Client-side throttle (requests per minute) shared by all threads."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(1, per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self.interval
        if wait > 0:
            time.sleep(wait)
