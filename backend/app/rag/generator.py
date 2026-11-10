"""Answer generation with Gemini (streaming and non-streaming)."""
from __future__ import annotations

from collections.abc import Iterator

from app.llm.base import LLMClient
from app.rag.guardrails import neutralize_markup
from app.rag.prompts import SYSTEM_PROMPT, answer_prompt


class AnswerGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _prompt(self, question: str, context: str, history: str) -> str:
        return answer_prompt(neutralize_markup(question), context, history)

    def generate(self, question: str, context: str, history: str = "") -> str:
        return self.llm.generate(self._prompt(question, context, history), system=SYSTEM_PROMPT)

    def stream(self, question: str, context: str, history: str = "") -> Iterator[str]:
        yield from self.llm.stream(self._prompt(question, context, history), system=SYSTEM_PROMPT)
