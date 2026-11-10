"""Guardrails: prompt-injection detection, query validation and output hygiene.

Uploaded documents are *untrusted data*. They are never concatenated into the
system prompt; they are wrapped in delimited ``<source>`` elements, any
delimiter look-alikes inside them are neutralised, and passages that look like
instructions to the model are flagged so the prompt can warn the model.
"""
from __future__ import annotations

import re

from app.core.exceptions import ValidationFailedError

_INJECTION_PATTERNS = [
    r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|messages)",
    r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|system)\b",
    r"\bforget\s+(everything|all|your)\s+(instructions|rules|previous)",
    r"\byou\s+are\s+now\s+(a|an|in)\b",
    r"\b(new|updated|override)\s+(system\s+)?(instructions?|prompt)\s*:",
    r"\bsystem\s*prompt\b",
    r"\bact\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+\w+\s+(without|with no)\s+(restrictions|rules)",
    r"\b(reveal|print|output|show)\s+(your|the)\s+(system|hidden|secret)\s+(prompt|instructions)",
    r"</?\s*(system|instructions?|source|context|assistant)\s*>",
    r"\bdo\s+not\s+(cite|mention)\s+(the\s+)?sources?\b",
    r"\bjailbreak\b|\bDAN\s+mode\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.I)
_TAG_RE = re.compile(r"<\s*/?\s*(source|context|system|instructions?|question|history|task|passage|answer)\b[^>]*>", re.I)


def detect_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def neutralize_markup(text: str) -> str:
    """Prevent document text from closing/opening our prompt delimiters."""
    return _TAG_RE.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)


def validate_query(query: str, max_chars: int = 4000) -> str:
    q = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", query).strip()
    if not q:
        raise ValidationFailedError("Question must not be empty")
    if len(q) > max_chars:
        raise ValidationFailedError(f"Question exceeds {max_chars} characters")
    if not re.search(r"\w", q):
        raise ValidationFailedError("Question must contain words")
    return q


_SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(sk|pk|rk)_(live|test)_[0-9A-Za-z]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "[REDACTED_TOKEN]"),
]


def redact_secrets(text: str) -> str:
    """Mask credentials that may appear in model output (sensitive data exposure guard)."""
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text
