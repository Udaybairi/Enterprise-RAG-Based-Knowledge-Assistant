"""Client IP resolution that cannot be spoofed with a forged X-Forwarded-For header."""
from __future__ import annotations

from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str:
    """The address of the client as seen by the outermost *trusted* proxy.

    Each trusted proxy appends the address it received the request from, so with N trusted hops
    the real client is the N-th entry from the right. Entries further left were supplied by the
    client and are ignored. With 0 hops the header is ignored and the socket peer is used.
    """
    hops = get_settings().effective_proxy_hops
    peer = request.client.host if request.client else "unknown"
    if hops <= 0:
        return peer
    fwd = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in fwd.split(",") if p.strip()]
    if len(parts) >= hops:
        return parts[-hops]
    return parts[0] if parts else peer
