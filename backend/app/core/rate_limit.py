"""In-process sliding-window rate limiter.

Limits are per process: adequate for a single API replica, weaker on serverless
platforms (each function instance counts separately). For horizontally scaled
deployments, swap :class:`SlidingWindowLimiter` for a Redis-backed
implementation with the same interface, or add edge rate-limiting rules.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.core.net import client_ip


class SlidingWindowLimiter:
    SWEEP_EVERY = 1000  # requests between sweeps of idle keys

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls = 0
        self._max_window = 0.0

    def _sweep(self, now: float) -> None:
        """Drop keys with no hits inside the largest window seen, so memory stays bounded."""
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - self._max_window]
        for k in stale:
            del self._hits[k]

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            self._max_window = max(self._max_window, window)
            self._calls += 1
            if self._calls % self.SWEEP_EVERY == 0:
                self._sweep(now)
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, window - (now - q[0])
            q.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _client_key(request: Request) -> str:
    user = getattr(request.state, "user_id", None)
    if user:
        return f"user:{user}"
    return f"ip:{client_ip(request)}"


def rate_limit(bucket: str):
    """Return a FastAPI dependency enforcing the configured limit for ``bucket``."""

    def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = {
            "chat": settings.rate_limit_chat,
            "upload": settings.rate_limit_upload,
            "auth": settings.rate_limit_auth,
        }.get(bucket, settings.rate_limit_default)
        ok, retry = limiter.hit(f"{bucket}:{_client_key(request)}", limit, settings.rate_limit_window_seconds)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please retry later.",
                headers={"Retry-After": str(int(retry) + 1)},
            )

    return dependency
