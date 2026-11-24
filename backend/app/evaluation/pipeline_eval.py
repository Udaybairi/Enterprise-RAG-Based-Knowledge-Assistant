"""End-to-end evaluation through the PRODUCTION code path.

Unlike ``test_pipeline`` (an isolated in-memory index for quick strategy comparison), this runner:

1. uploads the corpus as real documents into a temporary private collection,
2. processes them with the real ingestion pipeline for each chunking strategy,
3. retrieves with the real ``Retriever`` (on PostgreSQL: pgvector + tsvector in one SQL statement),
4. answers with the real ``RAGChain`` (configured Gemini models, prompts, citation validation),
5. deletes everything it created.

Outputs a JSON report and a Markdown summary with full provenance (git commit, prompt version,
models actually used, embedding model, dataset/corpus hashes, settings), so results can be
reproduced and compared over time.

    python -m app.evaluation.pipeline_eval --out ../docs/evaluation \\
        --chunking structure recursive semantic --retrieval semantic hybrid keyword mmr \\
        --generation structure:hybrid --max-generation 40

Run it against a scratch database (it creates and removes a user and a collection).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.security import hash_password
from app.database.models import Chunk, Collection, Document, User
from app.database.repositories import CollectionRepository, UserRepository
from app.database.session import get_engine, session_scope
from app.embeddings.factory import get_embedder
from app.evaluation import metrics as M
from app.evaluation.test_pipeline import DATA_DIR, load_dataset
from app.ingestion.pipeline import process_document
from app.llm.factory import get_llm
from app.rag.chain import RAGChain, app_version
from app.rag.citation_manager import is_refusal
from app.rag.prompts import PROMPT_VERSION
from app.retrieval.retriever import RetrievalConfig, Retriever
from app.services import document_service

log = get_logger(__name__)


class QueryCache:
    """Embed each distinct question once per run (questions repeat across configurations)."""

    def __init__(self, base):
        self.base = base
        self.cache: dict[str, np.ndarray] = {}
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.base, name)

    def embed_queries(self, texts):
        missing = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if missing:
            self.calls += 1
            for t, v in zip(missing, self.base.embed_queries(missing)):
                self.cache[t] = v
        return np.vstack([self.cache[t] for t in texts])

    def embed_query(self, text):
        return self.embed_queries([text])[0]


def _hash_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _git_sha() -> str:
    """Commit of the code that ran, with +dirty when the working tree differs from it."""
    here = str(Path(__file__).resolve().parent)
    try:
        sha = subprocess.check_output(["git", "-C", here, "rev-parse", "--short", "HEAD"], text=True,
                                      stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "-C", here, "status", "--porcelain"], text=True,
                                        stderr=subprocess.DEVNULL).strip()
        return f"{sha}+dirty" if dirty else sha
    except Exception:  # noqa: BLE001
        return app_version()


def _setup(corpus: list[Path]) -> tuple[str, str, dict[str, str]]:
    with session_scope() as db:
        email = f"eval-{uuid.uuid4().hex[:8]}@evaluation.invalid"
        user = UserRepository(db).create(email, hash_password(uuid.uuid4().hex + "A1"), "Evaluation runner")
        col = CollectionRepository(db).create(user.id, f"evaluation-{uuid.uuid4().hex[:6]}", "temporary", "private")
        docs = {}
        for p in corpus:
            d = document_service.create_document(db, user, col, p.name, p.read_bytes())
            docs[p.name] = d.id
        return user.id, col.id, docs


def _teardown(user_id: str, collection_id: str) -> None:
    with session_scope() as db:
        col = db.get(Collection, collection_id)
        if col is not None:
            document_service.delete_collection_data(db, col)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)


def _process_all(doc_ids: dict[str, str], strategy: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    for doc_id in doc_ids.values():
        process_document(doc_id, strategy=strategy)
    with session_scope() as db:
        statuses = {d.filename: (d.status, d.chunk_count, d.error_message)
                    for d in db.query(Document).filter(Document.id.in_(list(doc_ids.values())))}
    failed = {k: v[2] for k, v in statuses.items() if v[0] != "completed"}
    if failed:
        raise RuntimeError(f"ingestion failed for {failed}")
    return {"chunks": sum(v[1] for v in statuses.values()), "ingest_s": round(time.perf_counter() - t0, 1)}


def _relevant_counts(collection_id: str, dataset: list[dict]) -> dict[str, int]:
    """How many chunks in the index are relevant to each question (for ideal DCG)."""
    with session_scope() as db:
        rows = db.query(Chunk.text, Document.filename).join(Document, Document.id == Chunk.document_id) \
            .filter(Chunk.collection_id == collection_id).all()
    return {d["id"]: sum(1 for t, f in rows if M.is_relevant(t, f, d.get("source_documents", []), d.get("evidence", [])))
            for d in dataset}


def evaluate_retrieval(retriever: Retriever, collection_id: str, dataset: list[dict], cfg: RetrievalConfig,
                       n_relevant: dict[str, int]) -> dict[str, Any]:
    rows = []
    for item in dataset:
        t0 = time.perf_counter()
        hits = retriever.retrieve([item["question"]], [collection_id], cfg)
        ms = (time.perf_counter() - t0) * 1000
        row = {"id": item["id"], "category": item.get("category"), "latency_ms": round(ms, 1),
               "retrieved": [{"document": h.filename, "section": h.section, "cosine": round(h.vector_score or 0, 4)}
                             for h in hits]}
        if item.get("answerable", True):
            gold, ev = item.get("source_documents", []), item.get("evidence", [])
            rel = [M.is_relevant(h.text, h.filename, gold, ev) for h in hits]
            row.update(M.retrieval_metrics([(h.text, h.filename) for h in hits], gold, ev))
            row["ndcg"] = M.ndcg_at_k(rel, n_relevant.get(item["id"], 0), cfg.top_k)
            for k in (1, 3):
                row[f"recall@{k}"] = M.retrieval_metrics([(h.text, h.filename) for h in hits[:k]], gold, ev)["recall"]
        else:
            row["returned_for_unanswerable"] = len(hits)
        rows.append(row)
    ans = [r for r in rows if "recall" in r]
    lat = [r["latency_ms"] for r in rows]
    summary = {k: M.mean([r[k] for r in ans]) for k in ("precision", "recall", "hit_rate", "mrr", "ndcg",
                                                         "recall@1", "recall@3")}
    summary.update({"latency_p50_ms": M.percentile(lat, 50), "latency_p95_ms": M.percentile(lat, 95)})
    by_cat: dict[str, list] = defaultdict(list)
    for r in ans:
        by_cat[r["category"]].append(r["recall"])
    summary["recall_by_category"] = {c: M.mean(v) for c, v in sorted(by_cat.items())}
    return {"metrics": summary, "questions": rows}


def calibrate(retriever: Retriever, collection_id: str, dataset: list[dict], fetch_k: int = 20) -> dict[str, Any]:
    """Cosine distributions of relevant vs irrelevant chunks, and the best match for unanswerable questions.

    Recommends the highest threshold that still keeps the best relevant chunk for >= 95% of
    answerable questions (a recall-preserving choice), and reports what it filters out.
    """
    cfg = RetrievalConfig.from_settings(strategy="semantic", top_k=fetch_k, fetch_k=fetch_k,
                                        similarity_threshold=-1.0, reranker="none")
    best_rel, irrelevant, best_unans = [], [], []
    for item in dataset:
        hits = retriever.retrieve([item["question"]], [collection_id], cfg)
        cos = [h.vector_score or 0.0 for h in hits]
        if item.get("answerable", True):
            rel = [M.is_relevant(h.text, h.filename, item["source_documents"], item["evidence"]) for h in hits]
            rel_cos = [c for c, r in zip(cos, rel) if r]
            if rel_cos:
                best_rel.append(max(rel_cos))
            irrelevant += [c for c, r in zip(cos, rel) if not r]
        else:
            best_unans.append(max(cos) if cos else 0.0)
    rec = float(np.percentile(best_rel, 5)) if best_rel else None

    def dist(v):
        return {"n": len(v), "min": round(min(v), 3), "p25": round(float(np.percentile(v, 25)), 3),
                "median": round(float(np.median(v)), 3), "max": round(max(v), 3)} if v else {"n": 0}

    return {
        "best_relevant_cosine": dist(best_rel),
        "irrelevant_cosine": dist(irrelevant),
        "best_cosine_for_unanswerable": dist(best_unans),
        "recommended_threshold": round(rec, 3) if rec is not None else None,
        "at_recommended": None if rec is None else {
            "answerable_keeping_evidence": round(sum(c >= rec for c in best_rel) / len(best_rel), 3),
            "irrelevant_chunks_filtered": round(sum(c < rec for c in irrelevant) / max(1, len(irrelevant)), 3),
            "unanswerable_fully_filtered": round(sum(c < rec for c in best_unans) / max(1, len(best_unans)), 3),
        },
    }


def stratified(dataset: list[dict]) -> list[dict]:
    """Round-robin over categories, so a quota-limited prefix still covers every question type."""
    by_cat: dict[str, list] = defaultdict(list)
    for d in dataset:
        by_cat[d.get("category", "factual")].append(d)
    out, i = [], 0
    while len(out) < len(dataset):
        for cat in sorted(by_cat):
            if i < len(by_cat[cat]):
                out.append(by_cat[cat][i])
        i += 1
    return out


def evaluate_generation(chain: RAGChain, collection_id: str, dataset: list[dict], cfg: RetrievalConfig,
                        limit: int) -> dict[str, Any]:
    rows = []
    for item in stratified(dataset)[:limit]:
        try:
            res = chain.run(item["question"], [collection_id], cfg=cfg, rewrite=False, multi_query=False)
        except Exception as exc:  # noqa: BLE001 - e.g. provider quota exhausted
            rows.append({"id": item["id"], "category": item.get("category"), "error": str(exc)[:200]})
            continue
        refused = is_refusal(res.answer)
        answerable = item.get("answerable", True)
        prov = res.provenance
        row = {"id": item["id"], "category": item.get("category"), "answer": res.answer, "refused": refused,
               "latency_ms": res.latency_ms, "answer_model": prov.get("answer_model"),
               "tokens": prov.get("tokens"), "model_calls": prov.get("model_calls"),
               "faithfulness": M.lexical_faithfulness(res.answer, res.contexts) if not refused else None,
               "correct_refusal": refused == (not answerable)}
        if answerable:
            row["answer_f1"] = M.token_f1(M.strip_citations(res.answer), item.get("reference_answer") or "")
            row["citation_accuracy"] = M.citation_accuracy(res.citations, item["source_documents"],
                                                           item["evidence"], {})
            row["hallucinated"] = (not refused) and (row["faithfulness"] or 0) < 0.5
        else:
            row["hallucinated"] = not refused
        if item.get("must_not_contain"):
            row["injection_resisted"] = not any(s.lower() in res.answer.lower() for s in item["must_not_contain"])
        rows.append(row)
    ok = [r for r in rows if "error" not in r]
    tok_in = [r["tokens"]["input_tokens"] for r in ok if r.get("tokens")]
    tok_out = [r["tokens"]["output_tokens"] for r in ok if r.get("tokens")]
    summary = {
        "questions_attempted": len(rows), "questions_answered": len(ok), "errors": len(rows) - len(ok),
        "answer_f1": M.mean([r.get("answer_f1") for r in ok]),
        "faithfulness_lexical": M.mean([r.get("faithfulness") for r in ok]),
        "citation_accuracy": M.mean([r.get("citation_accuracy") for r in ok]),
        "hallucination_rate": M.mean([1.0 if r["hallucinated"] else 0.0 for r in ok]),
        "refusal_accuracy": M.mean([1.0 if r["correct_refusal"] else 0.0 for r in ok]),
        "injection_resisted": M.mean([1.0 if r["injection_resisted"] else 0.0 for r in ok if "injection_resisted" in r]),
        "latency_p50_ms": M.percentile([r["latency_ms"] for r in ok], 50),
        "latency_p95_ms": M.percentile([r["latency_ms"] for r in ok], 95),
        "tokens_per_question": {"input_mean": M.mean(tok_in), "output_mean": M.mean(tok_out)},
        "models_used": sorted({r["answer_model"] for r in ok if r.get("answer_model")}),
    }
    return {"metrics": summary, "questions": rows}


def run(chunking: list[str], retrieval: list[str], top_k: int, generation: list[tuple[str, str]],
        max_generation: int, out_dir: Path | None, threshold: float | None = None,
        rerankers: list[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    get_engine()
    dataset = load_dataset()
    corpus = sorted((DATA_DIR / "corpus").iterdir())
    embedder = QueryCache(get_embedder())
    embedder.embed_queries([d["question"] for d in dataset])  # one batched call for all questions
    llm = get_llm()
    retriever = Retriever(embedder=embedder, llm=llm)
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "provenance": {
            "date": started.isoformat(timespec="seconds"), "git_commit": _git_sha(), "prompt_version": PROMPT_VERSION,
            "provider": llm.provider, "chat_model": settings.gemini_chat_model,
            "utility_model": settings.gemini_utility_model, "fallback_models": settings.gemini_fallback_models,
            "thinking_level": settings.gemini_thinking_level, "embedding_model": embedder.model_id,
            "vector_store": settings.vector_store, "database": get_engine().dialect.name,
            "dataset_size": len(dataset), "dataset_hash": _hash_files([DATA_DIR / "dataset.json"]),
            "corpus_hash": _hash_files(corpus), "top_k": top_k, "reranker": settings.reranker,
            "similarity_threshold": settings.similarity_threshold if threshold is None else threshold,
        },
        "retrieval": [], "calibration": {}, "generation": [],
    }
    user_id, col_id, docs = _setup(corpus)
    try:
        wanted_gen = {(c, r) for c, r in generation}
        for ch in chunking:
            ingest = _process_all(docs, ch)
            n_rel = _relevant_counts(col_id, dataset)
            log.info("chunking=%s: %s", ch, ingest)
            report["calibration"][ch] = calibrate(retriever, col_id, dataset)
            for rr in rerankers or [settings.reranker]:
                for rs in retrieval:
                    cfg = RetrievalConfig.from_settings(strategy=rs, top_k=top_k, similarity_threshold=threshold,
                                                        reranker=rr)
                    res = evaluate_retrieval(retriever, col_id, dataset, cfg, n_rel)
                    report["retrieval"].append({"chunking": ch, "retrieval": rs, "reranker": rr, **ingest, **res})
                    log.info("  %-8s %-8s R@1=%s mrr=%s", rs, rr, res["metrics"]["recall@1"], res["metrics"]["mrr"])
            for rs in [r for (c, r) in wanted_gen if c == ch]:
                cfg = RetrievalConfig.from_settings(strategy=rs, top_k=top_k, similarity_threshold=threshold)
                chain = RAGChain(llm=llm, retriever=retriever)
                gen = evaluate_generation(chain, col_id, dataset, cfg, max_generation)
                report["generation"].append({"chunking": ch, "retrieval": rs, **gen})
        report["query_embedding_calls"] = embedder.calls
    finally:
        _teardown(user_id, col_id)
    report["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = started.strftime("%Y%m%d-%H%M")
        (out_dir / f"eval-{stamp}.json").write_text(json.dumps(report, indent=1, default=str))
        (out_dir / f"eval-{stamp}.md").write_text(to_markdown(report))
    return report


def _f(v, digits=3):
    return "—" if v is None else (f"{v:.{digits}f}" if isinstance(v, float) else str(v))


def to_markdown(r: dict[str, Any]) -> str:
    p = r["provenance"]
    lines = [f"# Evaluation report ({p['date'][:10]})", "",
             "Produced by `python -m app.evaluation.pipeline_eval` through the production code path.", "",
             "## Provenance", "", "| | |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | `{v}` |" for k, v in p.items()]
    lines += ["", "## Retrieval (all questions with gold evidence)", "",
              "| Chunking | Retrieval | Reranker | Chunks | Recall@1 | Recall@3 | Recall@k | Precision@k | MRR | nDCG@k | p50 ms | p95 ms |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in r["retrieval"]:
        m = c["metrics"]
        lines.append(f"| {c['chunking']} | {c['retrieval']} | {c.get('reranker', '')} | {c['chunks']} | {_f(m['recall@1'])} | "
                     f"{_f(m['recall@3'])} | {_f(m['recall'])} | {_f(m['precision'])} | "
                     f"{_f(m['mrr'])} | {_f(m['ndcg'])} | {_f(m['latency_p50_ms'], 0)} | {_f(m['latency_p95_ms'], 0)} |")
    lines += ["", "### Recall@k by question category", "",
              "| Chunking | Retrieval | Reranker | " + " | ".join(sorted(r["retrieval"][0]["metrics"]["recall_by_category"])) + " |",
              "|---|---|---|" + "---|" * len(r["retrieval"][0]["metrics"]["recall_by_category"])]
    for c in r["retrieval"]:
        cats = c["metrics"]["recall_by_category"]
        lines.append(f"| {c['chunking']} | {c['retrieval']} | {c.get('reranker', '')} | " +
                     " | ".join(_f(cats[k]) for k in sorted(cats)) + " |")
    lines += ["", "## Similarity-threshold calibration (semantic search, top 20)", ""]
    for ch, cal in r["calibration"].items():
        lines += [f"**{ch} chunking** — recommended threshold `{_f(cal['recommended_threshold'])}`",
                  f"(keeps evidence for 95% of answerable questions): `{json.dumps(cal['at_recommended'])}`", "",
                  f"- best relevant cosine: `{json.dumps(cal['best_relevant_cosine'])}`",
                  f"- irrelevant cosine: `{json.dumps(cal['irrelevant_cosine'])}`",
                  f"- best cosine for unanswerable questions: `{json.dumps(cal['best_cosine_for_unanswerable'])}`", ""]
    if r["generation"]:
        lines += ["## Answers (real model)", "",
                  "| Config | Answered | Errors | Answer F1 | Faithfulness (lexical) | Citation acc. | Hallucination | Refusal acc. | Injection resisted | p50 ms | p95 ms | Tokens in/out |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for g in r["generation"]:
            m = g["metrics"]
            t = m["tokens_per_question"]
            lines.append(f"| {g['chunking']}+{g['retrieval']} | {m['questions_answered']}/{m['questions_attempted']} | {m['errors']} | "
                         f"{_f(m['answer_f1'])} | {_f(m['faithfulness_lexical'])} | {_f(m['citation_accuracy'])} | "
                         f"{_f(m['hallucination_rate'])} | {_f(m['refusal_accuracy'])} | {_f(m['injection_resisted'])} | "
                         f"{_f(m['latency_p50_ms'], 0)} | {_f(m['latency_p95_ms'], 0)} | "
                         f"{_f(t['input_mean'], 0)}/{_f(t['output_mean'], 0)} |")
        lines += ["", f"Models that produced the answers: `{r['generation'][0]['metrics']['models_used']}`"]
    return "\n".join(lines) + "\n"


def main() -> None:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunking", nargs="+", default=["structure", "recursive", "semantic"])
    ap.add_argument("--retrieval", nargs="+", default=["semantic", "hybrid", "keyword", "mmr"])
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--generation", nargs="*", default=[], help="chunking:retrieval configs to answer with the LLM")
    ap.add_argument("--max-generation", type=int, default=40)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--threshold", type=float, help="similarity threshold (default: SIMILARITY_THRESHOLD)")
    ap.add_argument("--rerankers", nargs="+", default=None, help="e.g. none lexical")
    a = ap.parse_args()
    setup_logging("INFO")
    gens = [tuple(g.split(":", 1)) for g in a.generation]
    r = run(a.chunking, a.retrieval, a.top_k, gens, a.max_generation, a.out, a.threshold, a.rerankers)
    print(to_markdown(r))


if __name__ == "__main__":  # pragma: no cover
    main()
