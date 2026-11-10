"""Document lifecycle: upload, reprocess, delete (with vector-index cleanup), preview."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.database.models import Collection, Document, DocumentStatus, User
from app.database.repositories import ChunkRepository, DocumentRepository
from app.ingestion.deduplication import file_hash
from app.ingestion.loaders import MIME_TYPES
from app.ingestion.validation import safe_filename, validate_upload
from app.retrieval.keyword_index import keyword_index
from app.services import file_storage
from app.services.jobs import submit_processing
from app.vectorstore.factory import get_vector_store

log = get_logger(__name__)


def create_document(db: Session, user: User, collection: Collection, filename: str, data: bytes) -> Document:
    ext = validate_upload(filename, data)
    digest = file_hash(data)
    dup = DocumentRepository(db).find_duplicate(collection.id, digest)
    if dup is not None:
        raise ConflictError(f"'{safe_filename(filename)}' is identical to existing document '{dup.filename}'")
    doc = Document(collection_id=collection.id, owner_id=user.id, filename=safe_filename(filename),
                   stored_path="", file_type=ext.lstrip("."), mime_type=MIME_TYPES.get(ext, "application/octet-stream"),
                   size_bytes=len(data), content_hash=digest, status=DocumentStatus.pending.value, meta={})
    db.add(doc)
    db.flush()
    file_storage.save(db, doc, data, ext)
    DocumentRepository(db).add_log(doc.id, "upload", f"Uploaded {doc.filename} ({len(data)} bytes)")
    return doc


def schedule(document_id: str, **kwargs) -> None:
    submit_processing(document_id, **kwargs)


def is_stale(doc: Document) -> bool:
    """A document stuck in processing (e.g. the worker/function was killed) can be retried."""
    updated = doc.updated_at
    if updated is None:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated > timedelta(minutes=get_settings().stale_processing_minutes)


def reset_for_reprocess(db: Session, doc: Document) -> None:
    if doc.status == DocumentStatus.processing.value and not is_stale(doc):
        raise ConflictError("Document is currently being processed")
    doc.status = DocumentStatus.pending.value
    doc.error_message = None
    DocumentRepository(db).add_log(doc.id, "reprocess", "Re-processing requested")


def delete_document(db: Session, doc: Document) -> None:
    """Delete vectors, chunks, the stored file and the DB row - consistently."""
    ids = ChunkRepository(db).ids_for_document(doc.id)
    store = get_vector_store()
    if ids:
        store.delete(doc.collection_id, ids)
    stored_path = doc.stored_path
    collection_id = doc.collection_id
    db.delete(doc)
    db.flush()
    file_storage.delete_local(stored_path)
    keyword_index.invalidate(collection_id)
    log.info("Deleted document %s (%d vectors)", doc.id, len(ids))


def delete_collection_data(db: Session, collection: Collection) -> None:
    store = get_vector_store()
    store.delete_namespace(collection.id)
    folder = get_settings().uploads_dir / collection.id
    db.delete(collection)
    db.flush()
    shutil.rmtree(folder, ignore_errors=True)
    keyword_index.invalidate(collection.id)
