from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database.models import AuditLog, Conversation, Message
from app.database.session import session_scope


def test_retention_deletes_only_expired_records(client, admin, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "audit_log_retention_days", 30)
    monkeypatch.setattr(s, "conversation_retention_days", 30)
    old = datetime.now(timezone.utc) - timedelta(days=45)
    with session_scope() as db:
        uid = admin[1]["id"]
        db.add(AuditLog(action="test.old", created_at=old))
        db.add(AuditLog(action="test.recent"))
        conv_old = Conversation(user_id=uid, title="old", updated_at=old)
        conv_new = Conversation(user_id=uid, title="recent")
        db.add_all([conv_old, conv_new])
        db.flush()
        db.add(Message(conversation_id=conv_old.id, role="user", content="old question"))
        old_id, new_id = conv_old.id, conv_new.id

    r = client.post("/api/admin/retention/run", headers=admin[0])
    assert r.status_code == 200 and r.json()["audit_logs_deleted"] >= 1 and r.json()["conversations_deleted"] >= 1
    with session_scope() as db:
        assert db.get(Conversation, old_id) is None and db.get(Conversation, new_id) is not None
        assert db.scalars(select(Message).where(Message.conversation_id == old_id)).all() == []
        actions = set(db.scalars(select(AuditLog.action)).all())
    assert "test.old" not in actions and "test.recent" in actions and "retention.run" in actions


def test_retention_endpoints_are_protected(client, alice, monkeypatch):
    assert client.post("/api/admin/retention/run", headers=alice[0]).status_code == 403
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret-value-for-cron")
    assert client.get("/api/cron/retention").status_code == 401
    assert client.get("/api/cron/retention", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/api/cron/retention", headers={"Authorization": "Bearer s3cret-value-for-cron"})
    assert ok.status_code == 200
    monkeypatch.setattr(get_settings(), "cron_secret", None)
    assert client.get("/api/cron/retention", headers={"Authorization": "Bearer "}).status_code == 401
