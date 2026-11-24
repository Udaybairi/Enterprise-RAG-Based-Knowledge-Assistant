"""Data retention: delete audit logs and conversations older than the configured windows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import get_logger
from app.database.models import AuditLog, Conversation

log = get_logger(__name__)


def run_retention(db: Session, now: datetime | None = None) -> dict:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    result = {"audit_logs_deleted": 0, "conversations_deleted": 0,
              "audit_log_retention_days": s.audit_log_retention_days,
              "conversation_retention_days": s.conversation_retention_days}
    if s.audit_log_retention_days > 0:
        cutoff = now - timedelta(days=s.audit_log_retention_days)
        result["audit_logs_deleted"] = db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff)).rowcount or 0
    if s.conversation_retention_days > 0:
        cutoff = now - timedelta(days=s.conversation_retention_days)
        ids = list(db.scalars(select(Conversation.id).where(Conversation.updated_at < cutoff)).all())
        for i in range(0, len(ids), 500):  # ORM delete so messages cascade on every database
            for conv in db.scalars(select(Conversation).where(Conversation.id.in_(ids[i:i + 500]))).all():
                db.delete(conv)
        result["conversations_deleted"] = len(ids)
    db.add(AuditLog(action="retention.run", details=result))
    db.flush()
    log.info("Retention run: %s", result)
    return result


def retention_status(db: Session) -> dict:
    s = get_settings()
    return {
        "audit_log_retention_days": s.audit_log_retention_days,
        "conversation_retention_days": s.conversation_retention_days,
        "scheduled": bool(s.cron_secret),
        "last_run": db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.action == "retention.run")),
    }
