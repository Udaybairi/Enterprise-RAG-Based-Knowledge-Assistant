"""Deterministic offline LLM used for tests and key-less local runs.

It never invents content: it answers *extractively* by selecting the context
sentences that overlap most with the question and cites their source numbers,
so the full RAG pipeline (citations, grounding, refusal) can be exercised
without network access.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from app.llm.base import LLMClient
from app.utils.text import content_terms, split_sentences

_SOURCE_RE = re.compile(r'<source id="(\d+)"[^>]*>(.*?)</source>', re.S)
_QUESTION_RE = re.compile(r"<question>(.*?)</question>", re.S)


class FakeLLM(LLMClient):
    provider = "fake"
    model = "fake-extractive-llm"

    def generate(self, prompt, *, system=None, temperature=None, max_tokens=None, json_mode=False,
                 utility=False) -> str:
        task = re.search(r"<task>(\w+)</task>", prompt)
        task_name = task.group(1) if task else "answer"
        if task_name == "rewrite":
            q = _QUESTION_RE.search(prompt)
            hist = re.search(r"<history>(.*?)</history>", prompt, re.S)
            question = q.group(1).strip() if q else ""
            if hist and re.search(r"\b(it|its|they|them|this|that|those|these|he|she)\b", question, re.I):
                prev = [l for l in hist.group(1).splitlines() if l.lower().startswith("user:")]
                if prev:
                    topic = " ".join(sorted(content_terms(prev[-1][5:]))[:6])
                    question = f"{question} (regarding {topic})"
            return json.dumps({"standalone_question": question})
        if task_name == "expand":
            q = _QUESTION_RE.search(prompt)
            question = q.group(1).strip() if q else ""
            terms = sorted(content_terms(question))
            return json.dumps({"queries": [" ".join(terms)] if terms else []})
        if task_name == "rerank":
            q = _QUESTION_RE.search(prompt)
            qt = content_terms(q.group(1)) if q else set()
            scores = []
            for sid, body in re.findall(r'<passage id="(\d+)">(.*?)</passage>', prompt, re.S):
                bt = content_terms(body)
                scores.append({"id": int(sid), "score": round(10 * len(qt & bt) / max(1, len(qt)), 2)})
            return json.dumps({"scores": scores})
        if task_name == "judge":
            return json.dumps(self._judge(prompt))
        return self._answer(prompt)

    def _judge(self, prompt: str) -> dict:
        ctx = re.search(r"<context>(.*?)</context>", prompt, re.S)
        ans = re.search(r"<answer>(.*?)</answer>", prompt, re.S)
        ctx_terms = content_terms(ctx.group(1) if ctx else "")
        sentences = split_sentences(ans.group(1) if ans else "")
        supported = 0
        for s in sentences:
            t = content_terms(s)
            if t and len(t & ctx_terms) / len(t) >= 0.6:
                supported += 1
        return {"supported": supported, "total": len(sentences)}

    def _answer(self, prompt: str) -> str:
        q = _QUESTION_RE.search(prompt)
        qt = content_terms(q.group(1)) if q else set()
        candidates = []
        for sid, body in _SOURCE_RE.findall(prompt):
            body = re.sub(r"^\[[^\]]*\]\s*", "", body.strip())
            for sent in split_sentences(body):
                st = content_terms(sent)
                overlap = len(qt & st)
                if overlap:
                    candidates.append((overlap / (len(qt) or 1), int(sid), sent.strip()))
        candidates.sort(key=lambda x: -x[0])
        picked, seen = [], set()
        for score, sid, sent in candidates:
            if score < 0.25 or sent in seen:
                continue
            seen.add(sent)
            picked.append(f"{sent.rstrip('.')} [{sid}].")
            if len(picked) == 3:
                break
        if not picked:
            return "I could not find enough information in the uploaded documents to answer this question."
        return " ".join(picked)

    def stream(self, prompt, *, system=None, temperature=None, max_tokens=None) -> Iterator[str]:
        text = self.generate(prompt, system=system)
        for tok in re.findall(r"\S+\s*", text):
            yield tok
