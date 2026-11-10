"""Data-access layer.

All access-control decisions for collections/documents are centralised here so
that no route can accidentally leak another user's documents.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.database.models import (
    AuditLog,
    Chunk,
    Collection,
    Conversation,
    Document,
    DocumentStatus,
    EmbeddingCache,
    EvaluationRun,
    Message,
    ProcessingLog,
    Role,
    User,
    Visibility,
)


# --------------------------------------------------------------------------- users
class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def count(self) -> int:
        return self.db.scalar(select(func.count(User.id))) or 0

    def list(self) -> Sequence[User]:
        return self.db.scalars(select(User).order_by(User.created_at)).all()

    def create(self, email: str, hashed_password: str, full_name: str = "", role: str = Role.user.value) -> User:
        user = User(email=email.lower(), hashed_password=hashed_password, full_name=full_name, role=role)
        self.db.add(user)
        self.db.flush()
        return user


# --------------------------------------------------------------------- collections
class CollectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def _readable_clause(self, user: User):
        if user.is_admin:
            return True
        return or_(Collection.owner_id == user.id, Collection.visibility == Visibility.organization.value)

    def list_readable(self, user: User) -> Sequence[Collection]:
        stmt = select(Collection).order_by(Collection.created_at.desc())
        if not user.is_admin:
            stmt = stmt.where(self._readable_clause(user))
        return self.db.scalars(stmt).all()

    def readable_ids(self, user: User) -> list[str]:
        return [c.id for c in self.list_readable(user)]

    def get(self, collection_id: str) -> Collection | None:
        return self.db.get(Collection, collection_id)

    def get_by_name(self, owner_id: str, name: str) -> Collection | None:
        return self.db.scalar(
            select(Collection).where(Collection.owner_id == owner_id, func.lower(Collection.name) == name.lower())
        )

    @staticmethod
    def can_read(user: User, c: Collection) -> bool:
        return user.is_admin or c.owner_id == user.id or c.visibility == Visibility.organization.value

    @staticmethod
    def can_write(user: User, c: Collection) -> bool:
        return user.is_admin or c.owner_id == user.id

    def create(self, owner_id: str, name: str, description: str = "", visibility: str = "private") -> Collection:
        c = Collection(owner_id=owner_id, name=name, description=description, visibility=visibility)
        self.db.add(c)
        self.db.flush()
        return c

    def get_or_create_default(self, user: User) -> Collection:
        c = self.get_by_name(user.id, "My Documents")
        if c is None:
            c = self.create(user.id, "My Documents", "Default personal knowledge collection")
        return c

    def stats(self, collection_ids: Iterable[str]) -> dict[str, dict[str, int]]:
        ids = list(collection_ids)
        if not ids:
            return {}
        rows = self.db.execute(
            select(Document.collection_id, func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0),
                   func.coalesce(func.sum(Document.size_bytes), 0))
            .where(Document.collection_id.in_(ids))
            .group_by(Document.collection_id)
        ).all()
        out = {i: {"document_count": 0, "chunk_count": 0, "size_bytes": 0} for i in ids}
        for cid, n, chunks, size in rows:
            out[cid] = {"document_count": int(n), "chunk_count": int(chunks), "size_bytes": int(size)}
        return out


# ----------------------------------------------------------------------- documents
class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

    def list(
        self,
        collection_ids: list[str],
        *,
        search: str | None = None,
        status: str | None = None,
        file_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Document], int]:
        if not collection_ids:
            return [], 0
        stmt = select(Document).where(Document.collection_id.in_(collection_ids))
        if search:
            stmt = stmt.where(Document.filename.ilike(f"%{search}%"))
        if status:
            stmt = stmt.where(Document.status == status)
        if file_type:
            stmt = stmt.where(Document.file_type == file_type)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)).all()
        return rows, total

    def find_duplicate(self, collection_id: str, content_hash: str) -> Document | None:
        return self.db.scalar(
            select(Document).where(Document.collection_id == collection_id, Document.content_hash == content_hash)
        )

    def add_log(self, document_id: str, stage: str, message: str, level: str = "INFO",
                duration_ms: float | None = None) -> None:
        self.db.add(ProcessingLog(document_id=document_id, stage=stage, message=message, level=level,
                                  duration_ms=duration_ms))

    def counts_by_status(self, collection_ids: list[str]) -> dict[str, int]:
        out = {s.value: 0 for s in DocumentStatus}
        if not collection_ids:
            return out
        rows = self.db.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.collection_id.in_(collection_ids)).group_by(Document.status)
        ).all()
        for s, n in rows:
            out[s] = int(n)
        return out


# -------------------------------------------------------------------------- chunks
class ChunkRepository:
    def __init__(self, db: Session):
        self.db = db

    def for_collection(self, collection_id: str) -> Sequence[Chunk]:
        return self.db.scalars(
            select(Chunk).join(Document, Document.id == Chunk.document_id)
            .where(Chunk.collection_id == collection_id, Document.status == DocumentStatus.completed.value)
            .options(contains_eager(Chunk.document))
            .order_by(Chunk.document_id, Chunk.chunk_index)
        ).all()

    def by_ids(self, ids: Iterable[str]) -> dict[str, Chunk]:
        ids = list(ids)
        if not ids:
            return {}
        return {c.id: c for c in self.db.scalars(select(Chunk).where(Chunk.id.in_(ids))).all()}

    def ids_for_document(self, document_id: str) -> list[str]:
        return list(self.db.scalars(select(Chunk.id).where(Chunk.document_id == document_id)).all())

    def delete_for_document(self, document_id: str) -> None:
        self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))

    def count(self, collection_ids: list[str]) -> int:
        if not collection_ids:
            return 0
        return self.db.scalar(select(func.count(Chunk.id)).where(Chunk.collection_id.in_(collection_ids))) or 0

    def for_page(self, document_id: str, page: int | None) -> Sequence[Chunk]:
        stmt = select(Chunk).where(Chunk.document_id == document_id)
        if page is not None:
            stmt = stmt.where(Chunk.page_number == page)
        return self.db.scalars(stmt.order_by(Chunk.chunk_index)).all()


# ------------------------------------------------------------------ embedding cache
class EmbeddingCacheRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_many(self, hashes: list[str], model: str) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        uniq = list(dict.fromkeys(hashes))
        for i in range(0, len(uniq), 500):
            rows = self.db.scalars(
                select(EmbeddingCache).where(EmbeddingCache.model == model,
                                             EmbeddingCache.content_hash.in_(uniq[i:i + 500]))
            ).all()
            for r in rows:
                out[r.content_hash] = np.frombuffer(r.vector, dtype=np.float32).copy()
        return out

    def put_many(self, items: dict[str, np.ndarray], model: str) -> None:
        existing = set(self.get_many(list(items), model))
        for h, vec in items.items():
            if h in existing:
                continue
            v = np.asarray(vec, dtype=np.float32)
            self.db.add(EmbeddingCache(content_hash=h, model=model, dimension=int(v.shape[0]), vector=v.tobytes()))
        self.db.flush()


# ------------------------------------------------------------------- conversations
class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_user(self, user_id: str, limit: int = 100) -> Sequence[Conversation]:
        return self.db.scalars(
            select(Conversation).where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc()).limit(limit)
        ).all()

    def get_owned(self, conversation_id: str, user_id: str) -> Conversation | None:
        c = self.db.get(Conversation, conversation_id)
        return c if c and c.user_id == user_id else None

    def message_counts(self, ids: list[str]) -> dict[str, int]:
        if not ids:
            return {}
        rows = self.db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(ids)).group_by(Message.conversation_id)
        ).all()
        return {cid: int(n) for cid, n in rows}

    def add_message(self, conversation: Conversation, role: str, content: str,
                    citations: list[dict[str, Any]] | None = None, meta: dict[str, Any] | None = None) -> Message:
        m = Message(conversation_id=conversation.id, role=role, content=content,
                    citations=citations or [], meta=meta or {})
        self.db.add(m)
        conversation.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return m


# --------------------------------------------------------------------------- audit
class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(self, action: str, user_id: str | None = None, resource_type: str | None = None,
            resource_id: str | None = None, details: dict[str, Any] | None = None, ip: str | None = None) -> None:
        self.db.add(AuditLog(action=action, user_id=user_id, resource_type=resource_type,
                             resource_id=resource_id, details=details or {}, ip_address=ip))

    def recent(self, limit: int = 100, user_id: str | None = None) -> Sequence[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        return self.db.scalars(stmt).all()


# -------------------------------------------------------------------- evaluations
class EvaluationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self, limit: int = 20) -> Sequence[EvaluationRun]:
        return self.db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit)).all()

    def get(self, run_id: str) -> EvaluationRun | None:
        return self.db.get(EvaluationRun, run_id)


# ------------------------------------------------------------------- dashboard
def processing_activity(db: Session, collection_ids: list[str], days: int = 14) -> list[dict[str, Any]]:
    """Per-day uploads / completed / failed counts for the dashboard chart."""
    start = datetime.now(timezone.utc) - timedelta(days=days - 1)
    buckets: dict[str, dict[str, Any]] = {}
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        buckets[d] = {"date": d, "uploaded": 0, "completed": 0, "failed": 0}
    if collection_ids:
        docs = db.execute(
            select(Document.created_at, Document.status).where(
                Document.collection_id.in_(collection_ids), Document.created_at >= start.replace(hour=0, minute=0)
            )
        ).all()
        for created, status in docs:
            key = created.date().isoformat()
            if key in buckets:
                buckets[key]["uploaded"] += 1
                if status in ("completed", "failed"):
                    buckets[key][status] += 1
    return list(buckets.values())
