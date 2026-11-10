"""End-to-end ingestion pipeline for one document.

extract → preprocess → chunk → de-duplicate → embed (cached) → index → persist

Each stage is timed and written to ``processing_logs`` so the UI can show
exactly what happened. Re-processing is incremental: chunk IDs are
content-addressed, embeddings are cached by content hash, and only stale
vectors are deleted.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from datetime import datetime, timezone

from app.chunking.factory import get_chunker
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.database.models import Chunk, Document, DocumentStatus
from app.database.repositories import ChunkRepository, DocumentRepository
from app.database.session import session_scope
from app.embeddings.factory import get_embedder
from app.ingestion.deduplication import dedupe_exact, dedupe_near
from app.ingestion.loaders import load_document
from app.ingestion.preprocessing import preprocess
from app.ingestion.types import ChunkData
from app.retrieval.keyword_index import keyword_index
from app.services import file_storage
from app.utils.text import sha256_text
from app.vectorstore.factory import get_vector_store

log = get_logger(__name__)
_active: set[str] = set()
_active_lock = threading.Lock()


def chunk_id(document_id: str, content_hash: str, ordinal: int) -> str:
    return hashlib.sha1(f"{document_id}|{content_hash}|{ordinal}".encode()).hexdigest()


def embedding_text(filename: str, c: ChunkData) -> str:
    """Contextual text that is embedded: document + section headers help disambiguate chunks."""
    header = f"Document: {filename}"
    if c.section:
        header += f"\nSection: {c.section}"
    return f"{header}\n\n{c.text}"


class _Stage:
    def __init__(self, document_id: str, stage: str):
        self.document_id, self.stage = document_id, stage

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def done(self, message: str, level: str = "INFO") -> None:
        ms = (time.perf_counter() - self.t0) * 1000
        with session_scope() as db:
            DocumentRepository(db).add_log(self.document_id, self.stage, message, level, round(ms, 1))
        log.info("[%s] %s: %s (%.0f ms)", self.document_id[:8], self.stage, message, ms)

    def __exit__(self, *exc):
        return False


def process_document(document_id: str, *, strategy: str | None = None, chunk_size: int | None = None,
                     chunk_overlap: int | None = None) -> None:
    with _active_lock:
        if document_id in _active:
            log.info("Document %s already processing; skipping duplicate job", document_id)
            return
        _active.add(document_id)
    try:
        _process(document_id, strategy, chunk_size, chunk_overlap)
    finally:
        with _active_lock:
            _active.discard(document_id)


def _process(document_id: str, strategy, chunk_size, chunk_overlap) -> None:
    settings = get_settings()
    strategy = strategy or settings.chunking_strategy
    store = get_vector_store()
    t_start = time.perf_counter()

    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            log.warning("Document %s vanished before processing", document_id)
            return
        doc.status = DocumentStatus.processing.value
        doc.error_message = None
        DocumentRepository(db).add_log(document_id, "start", f"Processing started (strategy={strategy})")
        ext, filename, collection_id = "." + doc.file_type, doc.filename, doc.collection_id
        old_ids = set(ChunkRepository(db).ids_for_document(document_id))

    new_ids: list[str] = []
    try:
        with _Stage(document_id, "extract") as st, file_storage.materialize(document_id) as path:
            extracted = load_document(path, ext)
            st.done(f"Extracted {len(extracted.blocks)} raw blocks"
                    + (f" from {extracted.page_count} pages" if extracted.page_count else ""))

        with _Stage(document_id, "preprocess") as st:
            extracted, report = preprocess(extracted)
            st.done(
                f"{len(extracted.blocks)} blocks; {report.detected_headings} headings detected; "
                f"removed {report.removed_header_footer_lines} header/footer lines and "
                f"{report.removed_duplicate_paragraphs} duplicate paragraphs"
            )
            for w in report.warnings:
                st.done(w, level="WARNING")

        with _Stage(document_id, "chunk") as st:
            chunker = get_chunker(strategy, chunk_size, chunk_overlap)
            chunks = chunker.chunk(extracted)
            chunks, exact = dedupe_exact(chunks, key=lambda c: c.text)
            chunks, near = dedupe_near(chunks, key=lambda c: c.text, threshold=0.9)
            for i, c in enumerate(chunks):
                c.chunk_index = i
            if not chunks:
                raise AppError("Chunking produced no content")
            avg = sum(c.token_count for c in chunks) / len(chunks)
            st.done(f"{len(chunks)} chunks via '{chunker.name}' (avg {avg:.0f} tokens); "
                    f"dropped {exact} exact and {near} near-duplicate chunks")

        with _Stage(document_id, "embed") as st:
            embedder = get_embedder()
            vectors = embedder.embed_documents([embedding_text(filename, c) for c in chunks])
            st.done(f"Embedded {len(chunks)} chunks with {embedder.model_id}")

        hashes = [sha256_text(c.text) for c in chunks]
        ordinals: Counter[str] = Counter()
        for h in hashes:
            new_ids.append(chunk_id(document_id, h, ordinals[h]))
            ordinals[h] += 1
        metadatas = [{
            "document_id": document_id,
            "collection_id": collection_id,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            "section": (c.section or "")[:500],
            "file_type": ext.lstrip("."),
            "filename": filename,
        } for c in chunks]

        with _Stage(document_id, "index") as st:
            store.upsert(collection_id, new_ids, vectors, metadatas)
            stale = list(old_ids - set(new_ids))
            if stale:
                store.delete(collection_id, stale)
            st.done(f"Indexed {len(new_ids)} vectors in {store.name}; removed {len(stale)} stale vectors")

        with session_scope() as db:
            ChunkRepository(db).delete_for_document(document_id)
            db.flush()
            for cid, h, c in zip(new_ids, hashes, chunks):
                meta = dict(c.meta)
                if c.page_end and c.page_end != c.page_number:
                    meta["page_end"] = c.page_end
                db.add(Chunk(id=cid, document_id=document_id, collection_id=collection_id,
                             chunk_index=c.chunk_index, text=c.text, content_hash=h, page_number=c.page_number,
                             section=(c.section or None) and c.section[:500], token_count=c.token_count, meta=meta))
            doc = db.get(Document, document_id)
            if doc is None:  # deleted while processing → clean up vectors we just wrote
                raise AppError("Document was deleted during processing")
            doc.status = DocumentStatus.completed.value
            doc.chunk_count = len(chunks)
            doc.page_count = extracted.page_count
            doc.chunking_strategy = strategy
            doc.embedding_model = embedder.model_id
            doc.vector_store = store.name
            doc.processed_at = datetime.now(timezone.utc)
            doc.meta = {**(doc.meta or {}), **extracted.metadata, "paginated": extracted.paginated,
                        "suspicious_chunks": sum(1 for c in chunks if c.meta.get("suspicious")),
                        "chunk_size": chunk_size or settings.chunk_size,
                        "chunk_overlap": settings.chunk_overlap if chunk_overlap is None else chunk_overlap}
            total_ms = (time.perf_counter() - t_start) * 1000
            DocumentRepository(db).add_log(document_id, "complete", "Document ready for retrieval", "INFO",
                                           round(total_ms, 1))
        keyword_index.invalidate(collection_id)
        log.info("Document %s processed: %d chunks in %.0f ms", document_id, len(chunks),
                 (time.perf_counter() - t_start) * 1000)
    except Exception as exc:  # noqa: BLE001
        msg = exc.message if isinstance(exc, AppError) else f"{type(exc).__name__}: {exc}"
        log.exception("Processing failed for %s", document_id)
        # roll back vectors written in this run that are not referenced by the DB
        try:
            orphan = [i for i in new_ids if i not in old_ids]
            if orphan:
                store.delete(collection_id, orphan)
        except Exception:  # noqa: BLE001
            log.exception("Vector cleanup after failure failed")
        with session_scope() as db:
            doc = db.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.failed.value
                doc.error_message = msg[:2000]
                DocumentRepository(db).add_log(document_id, "error", msg[:2000], "ERROR")
        keyword_index.invalidate(collection_id)
