"""Postgres hybrid retrieval (pgvector + tsvector in one SQL statement). Runs in the pgvector config."""
from __future__ import annotations

import pytest
from sqlalchemy import event

import sample_files as sf
from app.retrieval.pg_hybrid import tsquery_terms
from app.retrieval.retriever import RetrievalConfig, Retriever
from app.vectorstore.factory import get_vector_store


def test_tsquery_terms_are_or_joined_and_injection_safe():
    assert tsquery_terms("How many days of annual leave?") == "many | days | annual | leave"
    hostile = "leave' & !(x) | foo:* <-> bar"
    terms = tsquery_terms(hostile)
    assert set(terms.replace(" | ", " ").split()) <= {"leave", "x", "foo", "bar"}
    assert not any(ch in terms for ch in "&!():*<>'")
    assert tsquery_terms("the and of") == ""


pg_only = pytest.mark.skipif(get_vector_store().name != "pgvector", reason="pgvector configuration only")


@pg_only
def test_one_round_trip_for_all_queries_and_collections(client, alice, tmp_dir):
    headers, _ = alice
    cols = []
    for i in range(3):
        col = client.post("/api/collections", headers=headers, json={"name": f"Batch {i}"}).json()
        p = sf.make_txt(tmp_dir / f"batch{i}.txt", f"Collection {i} policy: badge colour code is BLUE-{i}. "
                                                    f"Visitors must sign in at reception {i}.")
        client.post("/api/documents/upload", headers=headers, data={"collection_id": col["id"]},
                    files=[("files", (p.name, p.read_bytes()))])
        cols.append(col["id"])
    retriever = Retriever()
    assert retriever.pg is not None
    statements: list[str] = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    engine = retriever.pg.engine
    retriever.store._ensure_schema()
    event.listen(engine, "before_cursor_execute", count)
    try:
        hits = retriever.retrieve(["visitor sign in", "reception rules", "badge colour"], cols,
                                  RetrievalConfig.from_settings(strategy="hybrid", top_k=6, similarity_threshold=0.0))
    finally:
        event.remove(engine, "before_cursor_execute", count)
    searches = [s for s in statements if "LATERAL" in s]
    assert len(searches) == 1  # 3 query variants x 3 collections -> one SQL search statement
    assert {h.collection_id for h in hits} <= set(cols) and len({h.collection_id for h in hits}) >= 2
    assert all(h.text and h.filename for h in hits)  # hydrated by the same statement


@pg_only
def test_full_text_finds_exact_codes(client, alice, tmp_dir):
    headers, _ = alice
    col = client.post("/api/collections", headers=headers, json={"name": "Codes"}).json()
    p = sf.make_txt(tmp_dir / "codes.txt",
                    "Maintenance procedures for the cooling system are documented elsewhere. "
                    "\n\nError ZX4471 means the coolant pump has failed and must be replaced by a technician.")
    client.post("/api/documents/upload", headers=headers, data={"collection_id": col["id"]},
                files=[("files", (p.name, p.read_bytes()))])
    hits = Retriever().retrieve(["what does zx4471 mean"], [col["id"]],
                                RetrievalConfig.from_settings(strategy="keyword", top_k=3, similarity_threshold=0.0))
    assert hits and "ZX4471" in hits[0].text and hits[0].keyword_score > 0


@pg_only
def test_failed_documents_are_never_returned(client, alice, tmp_dir):
    from app.database.models import Document
    from app.database.session import session_scope

    headers, _ = alice
    col = client.post("/api/collections", headers=headers, json={"name": "Status filter"}).json()
    p = sf.make_txt(tmp_dir / "status.txt", "The quarterly offsite takes place in Lisbon every spring.")
    doc = client.post("/api/documents/upload", headers=headers, data={"collection_id": col["id"]},
                      files=[("files", (p.name, p.read_bytes()))]).json()["documents"][0]
    cfg = RetrievalConfig.from_settings(strategy="hybrid", top_k=3, similarity_threshold=0.0)
    assert Retriever().retrieve(["quarterly offsite Lisbon"], [col["id"]], cfg)
    with session_scope() as db:
        db.get(Document, doc["id"]).status = "processing"
    assert Retriever().retrieve(["quarterly offsite Lisbon"], [col["id"]], cfg) == []
