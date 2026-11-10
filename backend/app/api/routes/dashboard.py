from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.database.models import Conversation, Document, Message, User
from app.database.repositories import (
    AuditRepository,
    ChunkRepository,
    CollectionRepository,
    DocumentRepository,
    processing_activity,
)
from app.database.session import get_db
from app.schemas.documents import DocumentOut

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col_ids = CollectionRepository(db).readable_ids(user)
    by_status = DocumentRepository(db).counts_by_status(col_ids)
    recent, total_docs = DocumentRepository(db).list(col_ids, limit=8)
    storage = 0
    by_type: list[dict] = []
    embedding_models: list[dict] = []
    if col_ids:
        storage = db.scalar(select(func.coalesce(func.sum(Document.size_bytes), 0))
                            .where(Document.collection_id.in_(col_ids))) or 0
        by_type = [{"file_type": t, "count": int(n)} for t, n in db.execute(
            select(Document.file_type, func.count(Document.id)).where(Document.collection_id.in_(col_ids))
            .group_by(Document.file_type)).all()]
        embedding_models = [{"model": m or "not embedded", "count": int(n)} for m, n in db.execute(
            select(Document.embedding_model, func.count(Document.id)).where(Document.collection_id.in_(col_ids))
            .group_by(Document.embedding_model)).all()]
    my_convs = db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == user.id)) or 0
    fb = db.execute(
        select(Message.feedback, func.count(Message.id)).join(Conversation)
        .where(Conversation.user_id == user.id, Message.role == "assistant").group_by(Message.feedback)
    ).all()
    feedback = {"positive": 0, "negative": 0, "none": 0}
    for v, n in fb:
        feedback["positive" if v == 1 else "negative" if v == -1 else "none"] += int(n)
    return {
        "total_documents": total_docs,
        "processed_documents": by_status["completed"],
        "failed_documents": by_status["failed"],
        "pending_documents": by_status["pending"] + by_status["processing"],
        "status_breakdown": by_status,
        "total_chunks": ChunkRepository(db).count(col_ids),
        "total_collections": len(col_ids),
        "storage_bytes": int(storage),
        "file_types": by_type,
        "embedding_status": embedding_models,
        "conversations": my_convs,
        "feedback": feedback,
        "activity": processing_activity(db, col_ids),
        "recent_documents": [DocumentOut.model_validate(d) for d in recent],
    }


@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, ge=1, le=1000), _: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    users = {u.id: u.email for u in db.scalars(select(User)).all()}
    return [{"id": a.id, "user_id": a.user_id, "user_email": users.get(a.user_id), "action": a.action,
             "resource_type": a.resource_type, "resource_id": a.resource_id, "details": a.details,
             "ip_address": a.ip_address, "created_at": a.created_at} for a in AuditRepository(db).recent(limit)]
