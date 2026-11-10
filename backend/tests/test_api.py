"""End-to-end API tests: auth, RBAC, tenant isolation, ingestion, retrieval, chat, citations, cleanup."""
from __future__ import annotations

import json

import pytest

import sample_files as sf
from app.vectorstore.factory import get_vector_store


def _upload(client, headers, path, collection_id=None, strategy=None):
    data = {}
    if collection_id:
        data["collection_id"] = collection_id
    if strategy:
        data["chunking_strategy"] = strategy
    with open(path, "rb") as f:
        r = client.post("/api/documents/upload", headers=headers, data=data,
                        files=[("files", (path.name, f.read()))])
    assert r.status_code == 202, r.text
    return r.json()


@pytest.fixture(scope="module")
def alice_kb(client, alice, tmp_dir):
    headers, _ = alice
    r = client.post("/api/collections", headers=headers, json={"name": "HR Policies", "description": "HR"})
    assert r.status_code == 201, r.text
    col = r.json()
    docs = {}
    for maker, name in [(sf.make_pdf, "handbook.pdf"), (sf.make_markdown, "security.md"),
                        (sf.make_docx, "handbook.docx"), (sf.make_csv, "products.csv")]:
        res = _upload(client, headers, maker(tmp_dir / name), col["id"])
        assert not res["rejected"], res
        docs[name] = res["documents"][0]["id"]
    return col, docs


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"


def test_auth_flow(client, admin, alice):
    _, admin_user = admin
    _, alice_user = alice
    assert admin_user["role"] == "admin"  # first user
    assert alice_user["role"] == "user"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "alice@acme.example", "password": "wrong-pass1"})
    assert r.status_code == 401
    r = client.post("/api/auth/register", json={"email": "weak@acme.example", "password": "short"})
    assert r.status_code == 422


def test_rbac(client, admin, alice):
    assert client.get("/api/users", headers=alice[0]).status_code == 403
    assert client.get("/api/audit-logs", headers=alice[0]).status_code == 403
    assert client.post("/api/evaluation/run", headers=alice[0], json={}).status_code == 403
    assert client.get("/api/users", headers=admin[0]).status_code == 200
    r = client.post("/api/collections", headers=alice[0], json={"name": "Shared", "visibility": "organization"})
    assert r.status_code == 403


def test_ingestion_completes(client, alice, alice_kb):
    headers, _ = alice
    col, docs = alice_kb
    for doc_id in docs.values():
        d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        assert d["status"] == "completed", d
        assert d["chunk_count"] > 0
        stages = [l["stage"] for l in d["logs"]]
        assert {"extract", "preprocess", "chunk", "embed", "index", "complete"} <= set(stages)
    pdf = client.get(f"/api/documents/{docs['handbook.pdf']}", headers=headers).json()
    assert pdf["page_count"] == 3
    listing = client.get("/api/documents", headers=headers, params={"collection_id": col["id"]}).json()
    assert listing["total"] == 4
    search = client.get("/api/documents", headers=headers, params={"search": "security"}).json()
    assert [d["filename"] for d in search["items"]] == ["security.md"]


def test_duplicate_and_invalid_uploads_rejected(client, alice, alice_kb, tmp_dir):
    headers, _ = alice
    col, _ = alice_kb
    res = client.post("/api/documents/upload", headers=headers, data={"collection_id": col["id"]},
                      files=[("files", ("handbook.pdf", (tmp_dir / "handbook.pdf").read_bytes())),
                             ("files", ("evil.exe", b"MZ\x90\x00")),
                             ("files", ("fake.pdf", b"hello"))]).json()
    assert res["documents"] == []
    reasons = {r["filename"]: r["reason"] for r in res["rejected"]}
    assert "identical" in reasons["handbook.pdf"]
    assert "not allowed" in reasons["evil.exe"]
    assert "not a valid PDF" in reasons["fake.pdf"]


def test_preview_and_file_download(client, alice, alice_kb):
    headers, _ = alice
    _, docs = alice_kb
    p = client.get(f"/api/documents/{docs['handbook.pdf']}/preview", headers=headers, params={"page": 2}).json()
    assert p["chunks"] and all(c["page_number"] == 2 for c in p["chunks"])
    assert "Remote Work" in p["chunks"][0]["text"]
    f = client.get(f"/api/documents/{docs['handbook.pdf']}/file", headers=headers)
    assert f.status_code == 200 and f.content.startswith(b"%PDF")


def test_search_endpoint(client, alice, alice_kb):
    headers, _ = alice
    col, docs = alice_kb
    for strategy in ("semantic", "hybrid", "mmr", "keyword"):
        r = client.post("/api/search", headers=headers, json={
            "query": "How many days of annual leave?", "collection_ids": [col["id"]],
            "options": {"strategy": strategy, "top_k": 3}})
        assert r.status_code == 200, r.text
        hits = r.json()["hits"]
        assert hits, strategy
        assert any("25 days" in h["text"] for h in hits), strategy
    # metadata filtering by document
    r = client.post("/api/search", headers=headers, json={
        "query": "password length", "options": {"document_ids": [docs["security.md"]]}}).json()
    assert r["hits"] and all(h["document_id"] == docs["security.md"] for h in r["hits"])


def test_chat_with_citations_and_followup(client, alice, alice_kb):
    headers, _ = alice
    col, docs = alice_kb
    r = client.post("/api/chat", headers=headers, json={
        "message": "How many days of annual leave do full-time employees accrue?",
        "collection_ids": [col["id"]], "stream": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["grounded"] is True
    assert "25 days" in data["answer"]
    assert data["citations"]
    cit = data["citations"][0]
    assert cit["document_name"] in ("handbook.pdf", "handbook.docx")
    assert f"[{cit['index']}]" in data["answer"]
    if cit["document_name"] == "handbook.pdf":
        assert cit["page_number"] == 1  # real page, never fabricated
    else:
        assert cit["page_number"] is None
    conv_id = data["conversation_id"]

    r2 = client.post("/api/chat", headers=headers, json={
        "message": "How far in advance must it be requested?", "conversation_id": conv_id,
        "collection_ids": [col["id"]], "stream": False}).json()
    assert r2["rewritten_query"] and "leave" in r2["rewritten_query"].lower()
    assert r2["citations"]

    conv = client.get(f"/api/chat/{conv_id}", headers=headers).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]

    # feedback + regenerate
    msg_id = conv["messages"][-1]["id"]
    fb = client.post(f"/api/chat/messages/{msg_id}/feedback", headers=headers, json={"rating": 1})
    assert fb.status_code == 200 and fb.json()["feedback"] == 1
    regen = client.post("/api/chat", headers=headers, json={
        "message": "regenerate", "conversation_id": conv_id, "regenerate": True, "stream": False}).json()
    assert regen["citations"]
    conv = client.get(f"/api/chat/{conv_id}", headers=headers).json()
    assert len(conv["messages"]) == 4


def test_unanswerable_question_refuses(client, alice, alice_kb):
    headers, _ = alice
    col, _ = alice_kb
    data = client.post("/api/chat", headers=headers, json={
        "message": "What is the quarterly marketing budget for Antarctica?", "collection_ids": [col["id"]],
        "stream": False}).json()
    assert data["grounded"] is False
    assert data["citations"] == []
    assert "couldn't find enough information" in data["answer"]


def test_streaming_chat(client, alice, alice_kb):
    headers, _ = alice
    col, _ = alice_kb
    with client.stream("POST", "/api/chat", headers=headers, json={
            "message": "What are the password requirements?", "collection_ids": [col["id"]], "stream": True}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "meta" and types[-1] == "done"
    assert "token" in types and "status" in types
    final = next(e for e in events if e["type"] == "final")
    assert final["citations"] and final["message_id"]
    assert "14 characters" in final["answer"]
    streamed = "".join(e["content"] for e in events if e["type"] == "token")
    assert "14 characters" in streamed


def test_tenant_isolation(client, alice, bob, alice_kb):
    bob_h, _ = bob
    col, docs = alice_kb
    # bob cannot see alice's private collection or documents
    assert client.get(f"/api/collections/{col['id']}", headers=bob_h).status_code == 404
    assert client.get(f"/api/documents/{docs['handbook.pdf']}", headers=bob_h).status_code == 404
    assert client.get(f"/api/documents/{docs['handbook.pdf']}/file", headers=bob_h).status_code == 404
    assert client.delete(f"/api/documents/{docs['handbook.pdf']}", headers=bob_h).status_code == 404
    assert client.get("/api/documents", headers=bob_h).json()["total"] == 0
    # explicit request for alice's collection is denied
    r = client.post("/api/chat", headers=bob_h, json={"message": "annual leave days", "collection_ids": [col["id"]],
                                                      "stream": False})
    assert r.status_code == 404
    # implicit search over everything bob can read returns nothing from alice
    r = client.post("/api/search", headers=bob_h, json={"query": "annual leave days"}).json()
    assert r["hits"] == []
    data = client.post("/api/chat", headers=bob_h, json={"message": "How many days of annual leave?",
                                                         "stream": False}).json()
    assert data["citations"] == [] and data["grounded"] is False
    # conversations are private too
    convs = client.get("/api/chat/history", headers=alice[0]).json()
    assert client.get(f"/api/chat/{convs[0]['id']}", headers=bob_h).status_code == 404


def test_organization_collection_shared_read_only(client, admin, bob, tmp_dir):
    admin_h, _ = admin
    bob_h, _ = bob
    col = client.post("/api/collections", headers=admin_h,
                      json={"name": "Company Wide", "visibility": "organization"}).json()
    _upload(client, admin_h, sf.make_txt(tmp_dir / "office.txt"), col["id"])
    r = client.post("/api/search", headers=bob_h, json={"query": "cafeteria location"}).json()
    assert any("cafeteria" in h["text"] for h in r["hits"])
    doc_id = r["hits"][0]["document_id"]
    assert client.delete(f"/api/documents/{doc_id}", headers=bob_h).status_code == 403
    assert client.delete(f"/api/collections/{col['id']}", headers=bob_h).status_code == 403
    up = client.post("/api/documents/upload", headers=bob_h, data={"collection_id": col["id"]},
                     files=[("files", ("x.txt", b"some text here that is long enough"))])
    assert up.status_code == 403


def test_reprocess_with_other_strategy(client, alice, alice_kb):
    headers, _ = alice
    col, docs = alice_kb
    doc_id = docs["security.md"]
    before = client.get(f"/api/documents/{doc_id}", headers=headers).json()
    r = client.post(f"/api/documents/{doc_id}/reprocess", headers=headers,
                    json={"chunking_strategy": "semantic", "chunk_size": 300, "chunk_overlap": 0})
    assert r.status_code == 202, r.text
    after = client.get(f"/api/documents/{doc_id}", headers=headers).json()
    assert after["status"] == "completed" and after["chunking_strategy"] == "semantic"
    assert before["chunk_count"] > 0
    store = get_vector_store()
    total_chunks = sum(d["chunk_count"] for d in client.get(
        "/api/documents", headers=headers, params={"collection_id": col["id"]}).json()["items"])
    assert store.count(col["id"]) == total_chunks  # no stale vectors left behind


def test_delete_document_cleans_vectors(client, alice, alice_kb):
    headers, _ = alice
    col, docs = alice_kb
    store = get_vector_store()
    doc_id = docs["products.csv"]
    n_doc = client.get(f"/api/documents/{doc_id}", headers=headers).json()["chunk_count"]
    before = store.count(col["id"])
    assert client.delete(f"/api/documents/{doc_id}", headers=headers).status_code == 204
    assert store.count(col["id"]) == before - n_doc
    assert client.get(f"/api/documents/{doc_id}", headers=headers).status_code == 404
    r = client.post("/api/search", headers=headers, json={"query": "Laptop Pro warranty",
                                                          "collection_ids": [col["id"]]}).json()
    assert all(h["document_id"] != doc_id for h in r["hits"])


def test_dashboard_and_suggestions(client, alice, alice_kb):
    headers, _ = alice
    s = client.get("/api/dashboard/stats", headers=headers).json()
    assert s["processed_documents"] >= 3 and s["total_chunks"] > 0 and s["total_collections"] >= 2
    assert len(s["activity"]) == 14 and s["recent_documents"]
    sug = client.get("/api/chat/suggestions", headers=headers).json()
    assert isinstance(sug, list) and sug


def test_conversation_delete(client, alice):
    headers, _ = alice
    convs = client.get("/api/chat/history", headers=headers).json()
    cid = convs[-1]["id"]
    assert client.delete(f"/api/chat/{cid}", headers=headers).status_code == 204
    assert client.get(f"/api/chat/{cid}", headers=headers).status_code == 404


def test_audit_log_records_actions(client, admin):
    logs = client.get("/api/audit-logs", headers=admin[0]).json()
    actions = {l["action"] for l in logs}
    assert {"user.register", "document.upload", "chat.query", "document.delete"} <= actions


def test_delete_collection_removes_everything(client, alice, tmp_dir):
    headers, _ = alice
    col = client.post("/api/collections", headers=headers, json={"name": "Temp"}).json()
    _upload(client, headers, sf.make_txt(tmp_dir / "temp.txt", "Temporary note about quarterly planning."),
            col["id"])
    assert get_vector_store().count(col["id"]) > 0
    assert client.delete(f"/api/collections/{col['id']}", headers=headers).status_code == 204
    assert get_vector_store().count(col["id"]) == 0
    assert client.get(f"/api/collections/{col['id']}", headers=headers).status_code == 404


def test_rate_limiter_unit():
    from app.core.rate_limit import SlidingWindowLimiter

    lim = SlidingWindowLimiter()
    assert all(lim.hit("k", 3, 60)[0] for _ in range(3))
    ok, retry = lim.hit("k", 3, 60)
    assert not ok and retry > 0
