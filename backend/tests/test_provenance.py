"""Every answer must record what produced it (model, prompt, settings) and what it cost."""
from __future__ import annotations

import sample_files as sf
from app.rag.prompts import PROMPT_VERSION


def test_answer_records_provenance(client, bob, tmp_dir):
    headers, _ = bob
    col = client.post("/api/collections", headers=headers, json={"name": "Provenance"}).json()
    pdf = sf.make_pdf(tmp_dir / "prov.pdf", pages=2)
    client.post("/api/documents/upload", headers=headers, data={"collection_id": col["id"]},
                files=[("files", ("prov.pdf", pdf.read_bytes()))])
    r = client.post("/api/chat", headers=headers, json={
        "message": "How many days of annual leave do full-time employees accrue?",
        "collection_ids": [col["id"]], "stream": False}).json()
    p = r["provenance"]
    assert p["prompt_version"] == PROMPT_VERSION and len(PROMPT_VERSION) == 12
    assert p["answer_model"] == "fake-extractive-llm"
    assert p["embedding_model"].startswith("fake-hash-embedding@")
    assert p["retrieval_config"]["strategy"] and p["retrieval_config"]["top_k"]
    assert p["query_expansion"] == "adaptive"
    assert p["model_calls"] == len(p["calls"]) >= 1
    assert p["tokens"]["input_tokens"] > 0 and p["tokens"]["output_tokens"] > 0
    # persisted on the stored message
    conv = client.get(f"/api/chat/{r['conversation_id']}", headers=headers).json()
    assert conv["messages"][-1]["meta"]["provenance"]["prompt_version"] == PROMPT_VERSION


def test_adaptive_expansion_skips_the_extra_call_when_retrieval_is_strong(client, bob):
    headers, _ = bob
    # threshold 0: any real match counts as strong (fake embeddings produce low cosine values)
    strong = client.post("/api/chat", headers=headers, json={
        "message": "How many days of annual leave do full-time employees accrue?", "stream": False,
        "options": {"similarity_threshold": 0.0}}).json()
    assert strong["retrieval"]["expanded"] is False
    assert all(c["purpose"] != "query_expansion" for c in strong["provenance"]["calls"])
    always = client.post("/api/chat", headers=headers, json={
        "message": "How many days of annual leave do full-time employees accrue?", "stream": False,
        "options": {"multi_query": True}}).json()
    assert always["retrieval"]["expanded"] is True
    assert any(c["purpose"] == "query_expansion" for c in always["provenance"]["calls"])
