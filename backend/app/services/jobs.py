"""Background job runner for long-running ingestion work.

A bounded thread pool keeps the API responsive while documents are parsed and
embedded. Jobs are idempotent and their state lives in the database, so on
restart any document left in ``pending``/``processing`` is re-queued. For
multi-node deployments, replace this with a distributed queue (Celery/RQ/
Cloud Tasks) calling the same ``process_document`` function.
"""
from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import select

from app.core.logging import get_logger
from app.database.models import Document, DocumentStatus
from app.database.session import session_scope
from app.ingestion.pipeline import process_document

log = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=int(os.getenv("INGESTION_WORKERS", "2")), thread_name_prefix="ingest")
def run_inline() -> bool:
    """Run jobs inside the request: in tests (determinism) and on serverless platforms, where
    nothing may keep running after the response has been sent."""
    from app.config import get_settings

    return os.getenv("INGESTION_SYNC", "false").lower() == "true" or get_settings().serverless


def submit(fn, *args, **kwargs) -> Future | None:
    if run_inline():
        fn(*args, **kwargs)
        return None
    fut = _executor.submit(fn, *args, **kwargs)
    fut.add_done_callback(lambda f: f.exception() and log.error("job failed: %s", f.exception()))
    return fut


def submit_processing(document_id: str, **kwargs) -> Future | None:
    if run_inline():
        process_document(document_id, **kwargs)
        return None
    fut = _executor.submit(process_document, document_id, **kwargs)
    fut.add_done_callback(lambda f: f.exception() and log.error("job failed: %s", f.exception()))
    return fut


def requeue_unfinished() -> int:
    with session_scope() as db:
        ids = list(db.scalars(select(Document.id).where(
            Document.status.in_([DocumentStatus.pending.value, DocumentStatus.processing.value]))).all())
    for i in ids:
        submit_processing(i)
    if ids:
        log.info("Re-queued %d unfinished documents", len(ids))
    return len(ids)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
