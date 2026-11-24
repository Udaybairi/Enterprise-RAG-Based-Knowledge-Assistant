"""Regression tests for findings from the engineering audit."""
from __future__ import annotations

import threading

import numpy as np
import pytest
from starlette.requests import Request

import sample_files as sf
from app.config import get_settings
from app.core.net import client_ip
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import hash_password, verify_password
from app.database.repositories import ChunkRepository, UserRepository
from app.database.session import session_scope
from app.rag.citation_manager import process_citations
from app.rag.context_builder import build_context
from app.retrieval.types import RetrievedChunk
from app.vectorstore.factory import get_vector_store


# --- admin bootstrap ----------------------------------------------------------------------
def test_first_user_admin_off_by_default_in_production(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "first_user_is_admin", None)
    monkeypatch.setattr(s, "environment", "production")
    assert s.admin_on_first_registration is False
    monkeypatch.setattr(s, "environment", "development")
    assert s.admin_on_first_registration is True
    monkeypatch.setattr(s, "environment", "production")
    monkeypatch.setattr(s, "first_user_is_admin", True)  # only an explicit opt-in enables it
    assert s.admin_on_first_registration is True


def test_bootstrap_flag_can_be_claimed_only_once_under_concurrency(client):
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def claim():
        barrier.wait()
        with session_scope() as db:
            results.append(UserRepository(db).claim_flag("test_concurrent_claim"))

    threads = [threading.Thread(target=claim) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1 and len(results) == 8


def test_manage_cli_creates_and_promotes(client, monkeypatch, capsys):
    from app import manage

    monkeypatch.setenv("ADMIN_PASSWORD", "Sup3r-secure-admin-pw")
    assert manage.main(["create-admin", "--email", "ops@acme.example"]) == 0
    r = client.post("/api/auth/login", json={"email": "ops@acme.example", "password": "Sup3r-secure-admin-pw"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert manage.main(["demote", "--email", "ops@acme.example"]) == 0
    with pytest.raises(SystemExit):
        manage.main(["create-admin", "--email", "ops@acme.example"])  # already exists


# --- passwords ----------------------------------------------------------------------------
def test_passwords_over_72_bytes_are_rejected_not_truncated(client):
    base = "A1" + "x" * 70  # exactly 72 bytes
    assert verify_password(base, hash_password(base))
    long_pw = "ü" * 40 + "a1"  # 42 characters but 82 bytes
    with pytest.raises(ValueError):
        hash_password(long_pw)
    assert verify_password(base + "different-suffix", hash_password(base)) is False  # no truncation match
    r = client.post("/api/auth/register", json={"email": "long@acme.example", "password": long_pw})
    assert r.status_code == 422


# --- client IP / rate limiting --------------------------------------------------------------
def _request(xff: str | None, peer: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_forwarded_for_is_not_trusted_without_proxy_hops(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 0)
    assert client_ip(_request("6.6.6.6")) == "10.0.0.9"  # spoofed header ignored


def test_forwarded_for_uses_rightmost_trusted_hop(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_hops", 1)
    # client forged "6.6.6.6"; the trusted proxy appended the real address 203.0.113.7
    assert client_ip(_request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"


def test_rate_limiter_drops_idle_keys():
    lim = SlidingWindowLimiter()
    lim.SWEEP_EVERY = 10
    for i in range(9):
        lim.hit(f"k{i}", 5, 0.0001)
    import time

    time.sleep(0.01)
    lim.hit("fresh", 5, 0.0001)  # 10th call triggers a sweep
    assert set(lim._hits) <= {"fresh"}


# --- citations use the text the model actually saw -----------------------------------------
def test_citation_snippet_comes_from_truncated_context():
    long_text = "Alpha policy statement. " * 5 + "SECRET_TAIL beyond the budget. " * 400
    chunk = RetrievedChunk(chunk_id="c1", document_id="d", collection_id="c", text=long_text, filename="f.pdf")
    _, sources = build_context([chunk], max_tokens=200)
    assert sources[0].truncated and "SECRET_TAIL" not in sources[0].text[:60]
    res = process_citations("The alpha policy statement applies [1].", sources)
    cit = res.citations[0]
    assert cit["context_truncated"] is True
    assert cit["snippet"] in sources[0].text.replace("\n", " ") or cit["snippet"].rstrip("…") in sources[0].text


# --- ingestion consistency -------------------------------------------------------------------
def _upload(client, headers, path):
    r = client.post("/api/documents/upload", headers=headers, files=[("files", (path.name, path.read_bytes()))])
    assert r.status_code == 202, r.text
    return r.json()["documents"][0]


def test_failed_reprocess_keeps_previous_version_searchable(client, alice, tmp_dir, monkeypatch):
    headers, _ = alice
    doc = _upload(client, headers, sf.make_pdf(tmp_dir / "consistency.pdf", pages=3))
    store = get_vector_store()
    with session_scope() as db:
        before_ids = set(ChunkRepository(db).ids_for_document(doc["id"]))
    assert store.ids_for_document(doc["collection_id"], doc["id"]) == before_ids

    def boom(self, document_id):
        raise RuntimeError("simulated database failure during chunk replacement")

    monkeypatch.setattr(ChunkRepository, "delete_for_document", boom)
    r = client.post(f"/api/documents/{doc['id']}/reprocess", headers=headers,
                    json={"chunking_strategy": "recursive", "chunk_size": 200, "chunk_overlap": 20})
    assert r.status_code == 202
    monkeypatch.undo()

    d = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert d["status"] == "completed" and "previous version is still active" in d["error_message"]
    with session_scope() as db:
        after_ids = set(ChunkRepository(db).ids_for_document(doc["id"]))
    assert after_ids == before_ids  # SQL rolled back to the old version
    assert store.ids_for_document(doc["collection_id"], doc["id"]) == before_ids  # no lost, no orphan vectors
    hits = client.post("/api/search", headers=headers, json={
        "query": "annual leave days", "options": {"document_ids": [doc["id"]]}}).json()["hits"]
    assert hits and all(h["document_id"] == doc["id"] for h in hits)


def test_orphan_vectors_are_reconciled_on_reprocess_and_delete(client, alice, tmp_dir):
    headers, _ = alice
    doc = _upload(client, headers, sf.make_txt(tmp_dir / "orphans.txt", "Badges must be worn at all times on site."))
    store = get_vector_store()
    dim = get_settings().embedding_dimension
    orphan_vec = np.ones((1, dim), dtype=np.float32) / np.sqrt(dim)
    store.upsert(doc["collection_id"], ["orphan-1"], orphan_vec,
                 [{"document_id": doc["id"], "file_type": "txt"}])  # e.g. left by a killed run
    assert "orphan-1" in store.ids_for_document(doc["collection_id"], doc["id"])
    client.post(f"/api/documents/{doc['id']}/reprocess", headers=headers, json={})
    assert "orphan-1" not in store.ids_for_document(doc["collection_id"], doc["id"])

    store.upsert(doc["collection_id"], ["orphan-2"], orphan_vec, [{"document_id": doc["id"], "file_type": "txt"}])
    assert client.delete(f"/api/documents/{doc['id']}", headers=headers).status_code == 204
    assert store.ids_for_document(doc["collection_id"], doc["id"]) == set()


# --- health -----------------------------------------------------------------------------------
def test_health_details_admin_only_and_counts_model_failures(client, admin, alice, monkeypatch):
    assert client.get("/api/health/details").status_code == 401
    assert client.get("/api/health/details", headers=alice[0]).status_code == 403
    d = client.get("/api/health/details", headers=admin[0]).json()
    assert d["checks"] == {"database": "ok", "vector_store": "ok"}
    from app.api.routes import health

    monkeypatch.setattr(health, "model_status", lambda: {"checked": True, "ok": False, "message": "model missing"})
    d = client.get("/api/health/details", headers=admin[0]).json()
    assert d["status"] == "degraded" and d["models"]["ok"] is False
