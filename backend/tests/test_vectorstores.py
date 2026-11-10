from __future__ import annotations

import numpy as np
import pytest

from app.embeddings.gemini_embeddings import l2_normalize
from app.vectorstore.chroma_store import ChromaVectorStore
from app.vectorstore.faiss_store import FaissVectorStore


@pytest.fixture(params=["faiss", "chroma"])
def store_factory(request, tmp_path):
    cls = FaissVectorStore if request.param == "faiss" else ChromaVectorStore
    return lambda: cls(tmp_path, 16)


def _vecs(n, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, 16)))


def test_crud_filter_and_persistence(store_factory):
    s = store_factory()
    v = _vecs(10)
    ids = [f"c{i}" for i in range(10)]
    meta = [{"document_id": "d1" if i < 5 else "d2", "page_number": i, "file_type": "pdf", "section": None}
            for i in range(10)]
    s.upsert("col1", ids, v, meta)
    assert s.count("col1") == 10
    hits = s.search("col1", v[7], 3)
    assert hits[0].id == "c7" and hits[0].score == pytest.approx(1.0, abs=1e-4)
    assert hits[0].metadata["document_id"] == "d2"
    filtered = s.search("col1", v[7], 3, where={"document_id": ["d1"]})
    assert filtered and all(h.metadata["document_id"] == "d1" for h in filtered)
    # upsert existing id replaces vector rather than duplicating
    s.upsert("col1", ["c0"], v[9:10], [meta[0]])
    assert s.count("col1") == 10
    s.delete("col1", ["c7", "c8"])
    assert s.count("col1") == 8
    assert all(h.id not in ("c7", "c8") for h in s.search("col1", v[7], 10))
    vecs = s.get_vectors("col1", ["c1", "missing"])
    assert list(vecs) == ["c1"] and np.allclose(vecs["c1"], v[1], atol=1e-5)
    # namespaces are isolated
    assert s.search("other", v[0], 5) == []
    # reload from disk
    s2 = store_factory()
    assert s2.count("col1") == 8
    s2.delete_namespace("col1")
    assert s2.count("col1") == 0


def test_include_vectors_for_mmr(store_factory):
    s = store_factory()
    v = _vecs(4, seed=3)
    s.upsert("ns", ["a", "b", "c", "d"], v, [{"document_id": "x"}] * 4)
    hits = s.search("ns", v[0], 2, include_vectors=True)
    assert all(h.vector is not None and h.vector.shape == (16,) for h in hits)


def test_dimension_mismatch_rejected(tmp_path):
    s = FaissVectorStore(tmp_path, 16)
    with pytest.raises(ValueError):
        s.upsert("ns", ["a"], np.zeros((1, 8), dtype=np.float32), [{}])
