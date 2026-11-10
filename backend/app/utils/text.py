"""Small text utilities shared across ingestion, retrieval and evaluation."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache

STOPWORDS = frozenset(
    """a an the and or but if then else of to in on at for by with from as is are was were be been being it its
    this that these those there here what which who whom whose when where why how do does did done can could
    should would will shall may might must i you he she we they me him her us them my your our their not no
    yes so than too very just about into over under again further once all any both each few more most other
    some such only own same also please tell give show explain describe list""".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['\-][A-Za-z0-9]+)*")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _stem(t: str) -> str:
    for suf in ("ies", "ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


def keyword_tokens(text: str) -> list[str]:
    """Lower-cased, stop-word filtered, lightly stemmed tokens (BM25 / overlap)."""
    return [_stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def content_terms(text: str) -> set[str]:
    return set(keyword_tokens(text))


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_RE.split(text) if p and p.strip()]
    out: list[str] = []
    for p in parts:
        if len(p) > 600:
            out.extend(s.strip() for s in p.split("\n") if s.strip())
        else:
            out.append(re.sub(r"\s*\n\s*", " ", p))
    return out


@lru_cache(maxsize=1)
def _tiktoken_encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - offline or not installed
        return None


def count_tokens(text: str) -> int:
    """Token count via tiktoken when its BPE file is available, else a calibrated heuristic.

    Gemini's tokenizer is not public offline; both methods are approximations
    that are accurate enough for chunk sizing and context-window budgeting.
    """
    enc = _tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    words = len(_TOKEN_RE.findall(text))
    punct = len(re.findall(r"[^\w\s]", text))
    return int(words * 1.3 + punct * 0.5) + 1 if text else 0


def truncate_tokens(text: str, max_tokens: int) -> str:
    if count_tokens(text) <= max_tokens:
        return text
    words = text.split()
    lo, hi = 0, len(words)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(" ".join(words[:mid])) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return " ".join(words[:lo])
