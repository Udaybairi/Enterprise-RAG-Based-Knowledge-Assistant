"""Duplicate detection at three levels: documents, paragraphs/chunks, and retrieved context."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_for_hash(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def shingles(text: str, n: int = 5) -> set[str]:
    words = normalize_for_hash(text).split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[str], b: set[str]) -> float:
    """Fraction of ``a`` contained in ``b`` (detects a chunk that is a subset of another)."""
    if not a:
        return 0.0
    return len(a & b) / len(a)


def dedupe_exact(items: Sequence[T], key: Callable[[T], str], min_len: int = 0) -> tuple[list[T], int]:
    """Drop exact (normalised) duplicates, keeping the first occurrence."""
    seen: set[str] = set()
    out: list[T] = []
    removed = 0
    for it in items:
        text = key(it)
        norm = normalize_for_hash(text)
        if len(norm) >= min_len and norm in seen:
            removed += 1
            continue
        if len(norm) >= min_len:
            seen.add(norm)
        out.append(it)
    return out, removed


def dedupe_near(items: Sequence[T], key: Callable[[T], str], threshold: float = 0.85) -> tuple[list[T], int]:
    """Drop near-duplicates (shingle Jaccard / containment above ``threshold``), order-preserving."""
    kept: list[T] = []
    kept_sh: list[set[str]] = []
    removed = 0
    for it in items:
        sh = shingles(key(it))
        dup = any(jaccard(sh, k) >= threshold or containment(sh, k) >= 0.95 for k in kept_sh)
        if dup:
            removed += 1
            continue
        kept.append(it)
        kept_sh.append(sh)
    return kept, removed
