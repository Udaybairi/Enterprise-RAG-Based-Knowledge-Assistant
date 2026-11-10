"""Provider-agnostic LLM interface."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any


class LLMClient(ABC):
    provider: str = "base"
    model: str = ""

    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None, temperature: float | None = None,
                 max_tokens: int | None = None, json_mode: bool = False, utility: bool = False) -> str:
        """Return a full completion. ``utility`` selects the cheaper helper model."""

    @abstractmethod
    def stream(self, prompt: str, *, system: str | None = None, temperature: float | None = None,
               max_tokens: int | None = None) -> Iterator[str]:
        """Yield completion text deltas."""

    def generate_json(self, prompt: str, *, system: str | None = None, utility: bool = True) -> Any:
        raw = self.generate(prompt, system=system, json_mode=True, utility=utility, temperature=0.0)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> Any:
    """Parse JSON, tolerating markdown fences or surrounding prose."""
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S)
    if fence:
        raw = fence.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if m:
            return json.loads(m.group(1))
        raise
