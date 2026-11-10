"""Per-collection BM25 keyword index, built lazily from chunk text in the DB."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import func, select

from app.database.models import Chunk, Document, DocumentStatus
from app.database.repositories import ChunkRepository
from app.database.session import session_scope
from app.utils.text import keyword_tokens


@dataclass
class _Index:
    bm25: BM25Okapi | None
    ids: list[str]
    meta: list[dict]
    fingerprint: tuple = ()


def _fingerprint(db, collection_id: str) -> tuple:
    """Cheap change detector so caches in other processes/instances never serve stale results."""
    n, latest, docs = db.execute(
        select(func.count(Chunk.id), func.max(Document.processed_at), func.count(func.distinct(Document.id)))
        .select_from(Chunk).join(Document, Document.id == Chunk.document_id)
        .where(Chunk.collection_id == collection_id, Document.status == DocumentStatus.completed.value)
    ).one()
    return (int(n or 0), str(latest), int(docs or 0))


class KeywordIndex:
    def __init__(self) -> None:
        self._cache: dict[str, _Index] = {}
        self._lock = threading.Lock()

    def invalidate(self, collection_id: str) -> None:
        with self._lock:
            self._cache.pop(collection_id, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def _get(self, collection_id: str) -> _Index:
        with session_scope() as db:
            fp = _fingerprint(db, collection_id)
        with self._lock:
            idx = self._cache.get(collection_id)
        if idx is not None and idx.fingerprint == fp:
            return idx
        with session_scope() as db:
            chunks = ChunkRepository(db).for_collection(collection_id)
            corpus = [keyword_tokens(f"{c.section or ''} {c.text}") for c in chunks]
            ids = [c.id for c in chunks]
            meta = [{"document_id": c.document_id, "file_type": c.document.file_type} for c in chunks]
        bm25 = BM25Okapi(corpus) if corpus and any(corpus) else None
        idx = _Index(bm25, ids, meta, fp)
        with self._lock:
            self._cache[collection_id] = idx
        return idx

    def search(self, collection_id: str, query: str, k: int, where: dict | None = None) -> list[tuple[str, float]]:
        idx = self._get(collection_id)
        q = keyword_tokens(query)
        if idx.bm25 is None or not q:
            return []
        scores = idx.bm25.get_scores(q)
        order = scores.argsort()[::-1]
        out = []
        for i in order:
            if scores[i] <= 0:
                break
            if where and not all(idx.meta[i].get(key) in set(v) for key, v in where.items() if v):
                continue
            out.append((idx.ids[i], float(scores[i])))
            if len(out) >= k:
                break
        return out


keyword_index = KeywordIndex()
