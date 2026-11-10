"""Evaluation harness comparing chunking × retrieval strategies on a gold dataset.

The corpus is ingested into an *isolated*, temporary FAISS index (never the
production store) once per chunking strategy, using the same loaders,
preprocessing, chunkers, embeddings, retriever, reranker and RAG chain as
production. Each configuration is scored with the metrics in ``metrics.py``.

CLI:  python -m app.evaluation.test_pipeline --chunking recursive structure \
          --retrieval semantic hybrid mmr --no-generation
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from app.chunking.factory import get_chunker
from app.config import get_settings
from app.core.logging import get_logger
from app.embeddings.factory import get_embedder
from app.evaluation import metrics as M
from app.ingestion.deduplication import dedupe_exact
from app.ingestion.loaders import load_document
from app.ingestion.pipeline import embedding_text
from app.ingestion.preprocessing import preprocess
from app.llm.factory import get_llm
from app.rag.chain import RAGChain
from app.rag.citation_manager import is_refusal
from app.retrieval.retriever import RetrievalConfig, Retriever
from app.retrieval.types import RetrievedChunk
from app.utils.text import keyword_tokens
from app.vectorstore.faiss_store import FaissVectorStore

log = get_logger(__name__)
DATA_DIR = Path(__file__).parent / "data"
NAMESPACE = "evaluation"


def load_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    return json.loads((path or DATA_DIR / "dataset.json").read_text())


@dataclass
class _Chunk:
    id: str
    text: str
    filename: str
    section: str | None
    page: int | None


class InMemoryCorpus:
    """Chunk text + BM25 for the isolated evaluation index."""

    def __init__(self, chunks: list[_Chunk]):
        self.chunks = {c.id: c for c in chunks}
        self.ids = [c.id for c in chunks]
        self.bm25 = BM25Okapi([keyword_tokens(f"{c.section or ''} {c.text}") for c in chunks])

    def keyword_search(self, ns, query, k, where=None):
        q = keyword_tokens(query)
        if not q:
            return []
        scores = self.bm25.get_scores(q)
        order = np.argsort(scores)[::-1][:k]
        return [(self.ids[i], float(scores[i])) for i in order if scores[i] > 0]

    def hydrate(self, chunks: list[RetrievedChunk], allowed):
        out = []
        for c in chunks:
            src = self.chunks.get(c.chunk_id)
            if src is None:
                continue
            c.text, c.filename, c.section, c.page_number = src.text, src.filename, src.section, src.page
            c.document_id = src.filename
            c.file_type = Path(src.filename).suffix.lstrip(".")
            out.append(c)
        return out


def build_index(strategy: str, corpus_dir: Path, store: FaissVectorStore) -> InMemoryCorpus:
    embedder = get_embedder()
    chunks: list[_Chunk] = []
    texts: list[str] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in get_settings().allowed_extensions:
            continue
        doc, _ = preprocess(load_document(path))
        cs = get_chunker(strategy).chunk(doc)
        cs, _ = dedupe_exact(cs, key=lambda c: c.text)
        for c in cs:
            chunks.append(_Chunk(f"{path.name}:{c.chunk_index}", c.text, path.name, c.section, c.page_number))
            texts.append(embedding_text(path.name, c))
    vectors = embedder.embed_documents(texts)
    store.upsert(NAMESPACE, [c.id for c in chunks], vectors,
                 [{"document_id": c.filename, "file_type": Path(c.filename).suffix.lstrip(".")} for c in chunks])
    return InMemoryCorpus(chunks)


def evaluate_config(chain: RAGChain, retriever: Retriever, corpus: InMemoryCorpus, dataset: list[dict],
                    cfg: RetrievalConfig, generation: bool, judge) -> dict[str, Any]:
    embedder = get_embedder()
    rows = []
    for item in dataset:
        answerable = item.get("answerable", True)
        gold, evidence = item.get("source_documents", []), item.get("evidence", [])
        t0 = time.perf_counter()
        retrieved = retriever.retrieve([item["question"]], [NAMESPACE], cfg)
        retrieval_ms = (time.perf_counter() - t0) * 1000
        row: dict[str, Any] = {"id": item["id"], "question": item["question"], "answerable": answerable,
                               "retrieved": [{"document": c.filename, "section": c.section,
                                              "score": round(c.score, 4)} for c in retrieved],
                               "retrieval_latency_ms": round(retrieval_ms, 1)}
        qv = embedder.embed_query(item["question"])
        if retrieved:
            ctx_vecs = embedder.embed_documents([c.text for c in retrieved])
            row["context_relevance"] = float(np.mean([M.cosine(qv, v) for v in ctx_vecs]))
        else:
            row["context_relevance"] = None
        if answerable:
            row.update(M.retrieval_metrics([(c.text, c.filename) for c in retrieved], gold, evidence))
            row["context_precision"] = row["precision"]
        if generation:
            res = chain.run(item["question"], [NAMESPACE], cfg=cfg, rewrite=False, multi_query=False)
            refused = is_refusal(res.answer)
            row["answer"] = res.answer
            row["latency_ms"] = res.latency_ms
            row["refused"] = refused
            row["faithfulness"] = M.faithfulness(judge, res.answer, res.contexts)
            if answerable:
                row["answer_relevance"] = M.cosine(qv, embedder.embed_query(M.strip_citations(res.answer))) \
                    if not refused else 0.0
                row["answer_correctness"] = M.token_f1(M.strip_citations(res.answer), item["reference_answer"] or "")
                row["citation_accuracy"] = M.citation_accuracy(
                    res.citations, gold, evidence, {cid: corpus.chunks[cid].text for cid in corpus.chunks})
                row["hallucinated"] = (not refused) and row["faithfulness"] < 0.5
            else:
                row["hallucinated"] = not refused  # answering an unanswerable question
            row["correct_refusal"] = refused == (not answerable)
        rows.append(row)

    ans = [r for r in rows if r["answerable"]]
    summary = {
        "precision": M.mean([r.get("precision") for r in ans]),
        "recall": M.mean([r.get("recall") for r in ans]),
        "hit_rate": M.mean([r.get("hit_rate") for r in ans]),
        "mrr": M.mean([r.get("mrr") for r in ans]),
        "context_relevance": M.mean([r.get("context_relevance") for r in rows]),
        "retrieval_latency_ms": M.mean([r["retrieval_latency_ms"] for r in rows]),
    }
    if generation:
        summary.update({
            "answer_relevance": M.mean([r.get("answer_relevance") for r in ans]),
            "faithfulness": M.mean([r.get("faithfulness") for r in rows if not r.get("refused")]),
            "citation_accuracy": M.mean([r.get("citation_accuracy") for r in ans]),
            "answer_correctness": M.mean([r.get("answer_correctness") for r in ans]),
            "hallucination_rate": M.mean([1.0 if r.get("hallucinated") else 0.0 for r in rows]),
            "refusal_accuracy": M.mean([1.0 if r.get("correct_refusal") else 0.0 for r in rows]),
            "latency_ms": M.mean([r.get("latency_ms") for r in rows]),
        })
    return {"metrics": summary, "questions": rows}


def run_evaluation(chunking_strategies: list[str], retrieval_strategies: list[str], top_k: int = 4,
                   evaluate_generation: bool = True, dataset_path: Path | None = None,
                   corpus_dir: Path | None = None) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    corpus_dir = corpus_dir or DATA_DIR / "corpus"
    llm = get_llm()
    settings = get_settings()
    configs = []
    started = time.perf_counter()
    for chunking in chunking_strategies:
        with tempfile.TemporaryDirectory(prefix="rag-eval-") as tmp:
            store = FaissVectorStore(Path(tmp), settings.embedding_dimension)
            t0 = time.perf_counter()
            corpus = build_index(chunking, corpus_dir, store)
            index_ms = (time.perf_counter() - t0) * 1000
            retriever = Retriever(store=store, llm=llm, keyword_search=corpus.keyword_search,
                                  hydrate=corpus.hydrate)
            chain = RAGChain(llm=llm, retriever=retriever)
            for retrieval in retrieval_strategies:
                cfg = RetrievalConfig.from_settings(strategy=retrieval, top_k=top_k)
                log.info("Evaluating chunking=%s retrieval=%s", chunking, retrieval)
                res = evaluate_config(chain, retriever, corpus, dataset, cfg, evaluate_generation,
                                      llm if llm.provider != "fake" else None)
                configs.append({"chunking": chunking, "retrieval": retrieval, "chunks": len(corpus.ids),
                                "index_ms": round(index_ms, 1), **res})

    def score(c):
        m = c["metrics"]
        parts = [m.get("recall") or 0, m.get("mrr") or 0, m.get("precision") or 0]
        if evaluate_generation:
            parts += [m.get("faithfulness") or 0, 1 - (m.get("hallucination_rate") or 0)]
        return sum(parts) / len(parts)

    best = max(configs, key=score) if configs else None
    return {
        "dataset_size": len(dataset),
        "provider": llm.provider,
        "embedding_model": get_embedder().model_id,
        "top_k": top_k,
        "duration_s": round(time.perf_counter() - started, 2),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "configs": configs,
        "best": {"chunking": best["chunking"], "retrieval": best["retrieval"], "score": round(score(best), 4)}
        if best else None,
    }


def run_and_store(run_id: str, **kwargs) -> None:
    """Background entry point used by the API."""
    from app.database.models import EvaluationRun
    from app.database.session import session_scope

    try:
        results = run_evaluation(**kwargs)
        with session_scope() as db:
            run = db.get(EvaluationRun, run_id)
            run.status, run.results = "completed", results
            run.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        log.exception("evaluation failed")
        with session_scope() as db:
            run = db.get(EvaluationRun, run_id)
            run.status, run.error_message = "failed", str(exc)[:2000]
            run.finished_at = datetime.now(timezone.utc)


def main() -> None:  # pragma: no cover - CLI
    from app.core.logging import setup_logging
    from app.database.session import init_db

    p = argparse.ArgumentParser(description="Compare chunking and retrieval strategies")
    p.add_argument("--chunking", nargs="+", default=["recursive", "structure", "semantic"])
    p.add_argument("--retrieval", nargs="+", default=["semantic", "hybrid", "mmr"])
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--no-generation", action="store_true")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    setup_logging("INFO")
    init_db()
    res = run_evaluation(a.chunking, a.retrieval, a.top_k, not a.no_generation)
    header = f"{'chunking':<11}{'retrieval':<10}{'P@k':>7}{'R@k':>7}{'MRR':>7}{'ctxRel':>8}"
    if not a.no_generation:
        header += f"{'faith':>7}{'cite':>7}{'halluc':>8}{'lat_ms':>9}"
    print(header)
    for c in res["configs"]:
        m = c["metrics"]
        line = (f"{c['chunking']:<11}{c['retrieval']:<10}{m['precision'] or 0:>7.3f}{m['recall'] or 0:>7.3f}"
                f"{m['mrr'] or 0:>7.3f}{m['context_relevance'] or 0:>8.3f}")
        if not a.no_generation:
            line += (f"{m['faithfulness'] or 0:>7.3f}{m['citation_accuracy'] or 0:>7.3f}"
                     f"{m['hallucination_rate'] or 0:>8.3f}{m['latency_ms'] or 0:>9.0f}")
        print(line)
    print("best:", res["best"])
    if a.output:
        a.output.write_text(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
