"""Database-backed file storage (serverless) and recovery of interrupted processing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sample_files as sf
from app.config import get_settings
from app.database.models import Document, DocumentFile
from app.database.session import session_scope


def test_database_file_storage_roundtrip(client, alice, tmp_dir, monkeypatch):
    headers, _ = alice
    monkeypatch.setattr(get_settings(), "file_storage", "database")
    pdf = sf.make_pdf(tmp_dir / "db_stored.pdf", pages=2)
    r = client.post("/api/documents/upload", headers=headers,
                    files=[("files", ("db_stored.pdf", pdf.read_bytes()))])
    assert r.status_code == 202, r.text
    doc_id = r.json()["documents"][0]["id"]
    d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
    assert d["status"] == "completed" and d["page_count"] == 2  # processed from DB bytes via a temp file
    with session_scope() as db:
        assert db.get(Document, doc_id).stored_path.startswith("db://")
        assert db.get(DocumentFile, doc_id) is not None
    f = client.get(f"/api/documents/{doc_id}/file", headers=headers)
    assert f.status_code == 200 and f.content == pdf.read_bytes()
    assert "db_stored.pdf" in f.headers["content-disposition"]
    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 204
    with session_scope() as db:
        assert db.get(DocumentFile, doc_id) is None  # removed with the document


def test_stale_processing_document_can_be_recovered(client, alice, tmp_dir):
    headers, _ = alice
    txt = sf.make_txt(tmp_dir / "stuck.txt", "Quarterly security training is mandatory for every employee.")
    doc_id = client.post("/api/documents/upload", headers=headers,
                         files=[("files", ("stuck.txt", txt.read_bytes()))]).json()["documents"][0]["id"]
    with session_scope() as db:  # simulate a worker / serverless function killed mid-processing
        d = db.get(Document, doc_id)
        d.status = "processing"
        d.updated_at = datetime.now(timezone.utc)
    assert client.post(f"/api/documents/{doc_id}/reprocess", headers=headers, json={}).status_code == 409
    with session_scope() as db:
        db.get(Document, doc_id).updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    r = client.post(f"/api/documents/{doc_id}/reprocess", headers=headers, json={})
    assert r.status_code == 202
    assert client.get(f"/api/documents/{doc_id}", headers=headers).json()["status"] == "completed"


def test_serverless_settings(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATA_DIR", raising=False)
    s = Settings(database_url="postgres://u:p@host/db?sslmode=require")
    assert s.serverless is True
    assert str(s.data_dir).startswith("/tmp")
    assert s.effective_database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"


def test_production_requires_strong_secret(monkeypatch):
    import pytest

    from app import main

    monkeypatch.setattr(get_settings(), "environment", "production")
    monkeypatch.setattr(get_settings(), "jwt_secret_key", "short")
    with pytest.raises(RuntimeError):
        main._check_secrets()
