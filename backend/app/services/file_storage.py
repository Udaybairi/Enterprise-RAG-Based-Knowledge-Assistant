"""Storage for original uploaded files.

* ``local``    – files under ``DATA_DIR/uploads/<collection>/<document><ext>`` (servers with a disk).
* ``database`` – file bytes in the ``document_files`` table (serverless platforms such as Vercel,
  which have no persistent filesystem). Deleted automatically with the document row.

Loaders need a filesystem path, so ``materialize`` yields a real path in both modes (a temporary
file for database storage).
"""
from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.database.models import Document, DocumentFile
from app.database.session import session_scope

DB_PREFIX = "db://"


def save(db: Session, doc: Document, data: bytes, ext: str) -> None:
    settings = get_settings()
    if settings.file_storage == "database":
        db.add(DocumentFile(document_id=doc.id, data=data))
        doc.stored_path = f"{DB_PREFIX}{doc.id}"
        return
    target_dir = settings.uploads_dir / doc.collection_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{doc.id}{ext}"
    target.write_bytes(data)
    doc.stored_path = str(target)


def _local_path(doc: Document) -> Path:
    path = Path(doc.stored_path)
    root = get_settings().uploads_dir.resolve()
    if not path.resolve().is_relative_to(root) or not path.exists():
        raise NotFoundError("Stored file not found")
    return path


def read_bytes(db: Session, doc: Document) -> bytes:
    if doc.stored_path.startswith(DB_PREFIX):
        f = db.get(DocumentFile, doc.id)
        if f is None:
            raise NotFoundError("Stored file not found")
        return f.data
    return _local_path(doc).read_bytes()


@contextmanager
def materialize(document_id: str) -> Iterator[Path]:
    """Yield a filesystem path holding the document's original bytes."""
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise NotFoundError("Document not found")
        stored, ext = doc.stored_path, "." + doc.file_type
        data = read_bytes(db, doc) if stored.startswith(DB_PREFIX) else None
        local = None if data is not None else _local_path(doc)
    if local is not None:
        yield local
        return
    with tempfile.TemporaryDirectory(prefix="rag-doc-") as tmp:
        path = Path(tmp) / f"document{ext}"
        path.write_bytes(data)
        yield path


def delete_local(stored_path: str | None) -> None:
    """Remove a local file (database-stored files are removed by FK cascade)."""
    if stored_path and not stored_path.startswith(DB_PREFIX):
        p = Path(stored_path)
        if p.exists():
            p.unlink()
