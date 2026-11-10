from __future__ import annotations

import numpy as np
import pytest

import sample_files as sf
from app.chunking.factory import get_chunker
from app.chunking.semantic_chunker import SemanticChunker
from app.embeddings.fake_embeddings import FakeEmbeddings
from app.ingestion.loaders import load_document
from app.ingestion.preprocessing import preprocess
from app.ingestion.types import Block, ExtractedDocument


class _Emb:
    def __init__(self):
        self.base = FakeEmbeddings(256)
        self.calls = 0

    def embed_uncached(self, texts):
        self.calls += 1
        return self.base.embed_array(texts)


@pytest.fixture
def pdf_doc(tmp_path):
    doc, _ = preprocess(load_document(sf.make_pdf(tmp_path / "h.pdf", pages=3)))
    return doc


@pytest.mark.parametrize("strategy", ["recursive", "token", "structure", "semantic"])
def test_all_strategies_preserve_pages_and_sections(pdf_doc, strategy):
    chunks = get_chunker(strategy, 400, 60, embedder=_Emb()).chunk(pdf_doc)
    assert chunks
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.page_number in (1, 2, 3) for c in chunks)
    assert all(c.token_count > 0 for c in chunks)
    leave = next(c for c in chunks if "25 days" in c.text)
    assert leave.page_number == 1 and "Annual Leave" in (leave.section or "")


def _long_doc():
    topic_a = ("Solar panels convert sunlight into electricity using photovoltaic cells. "
               "Photovoltaic efficiency depends on panel temperature and sunlight angle. ") * 3
    topic_b = ("The cafeteria menu offers vegetarian pasta, fresh salads and soup every weekday. "
               "Lunch vouchers for the cafeteria are distributed monthly. ") * 3
    blocks = [Block("Report", "heading", heading_level=1, section=["Report"])]
    for t in (topic_a, topic_a, topic_b, topic_b):
        blocks.append(Block(t.strip(), "paragraph", section=["Report"]))
    return ExtractedDocument(blocks, 0, paginated=False)


def test_recursive_respects_size_and_overlap():
    chunks = get_chunker("recursive", 300, 80).chunk(_long_doc())
    assert all(len(c.text) <= 300 for c in chunks)
    # consecutive chunks share overlapping text
    assert any(chunks[i].text[-30:] in chunks[i + 1].text or chunks[i + 1].text[:30] in chunks[i].text
               for i in range(len(chunks) - 1))


def test_token_chunker_limits_tokens():
    from app.utils.text import count_tokens

    chunker = get_chunker("token", 400, 40)
    chunks = chunker.chunk(_long_doc())
    assert all(count_tokens(c.text) <= chunker.token_size + 5 for c in chunks)


def test_structure_chunker_never_crosses_sections():
    doc, _ = preprocess(ExtractedDocument([Block(
        "# A\n\nAlpha text about apples and orchards.\n\n# B\n\nBeta text about bridges and rivers.", "text")],
        0, paginated=False))
    from app.ingestion.loaders import load_markdown  # noqa: F401  (markdown parsing covered elsewhere)
    chunks = get_chunker("structure", 1000, 0).chunk(doc)
    for c in chunks:
        assert not ("apples" in c.text and "bridges" in c.text)


def test_structure_chunker_keeps_tables_whole(tmp_path):
    doc, _ = preprocess(load_document(sf.make_markdown(tmp_path / "s.md")))
    chunks = get_chunker("structure", 1000, 100).chunk(doc)
    table_chunk = next(c for c in chunks if "SEV1" in c.text)
    assert "SEV2" in table_chunk.text and "| Severity |" in table_chunk.text


def test_semantic_chunker_splits_on_topic_change():
    emb = _Emb()
    chunker = SemanticChunker(emb.embed_uncached, chunk_size=1200, breakpoint_percentile=60)
    chunks = chunker.chunk(_long_doc())
    assert emb.calls == 1  # one batched embedding call
    assert len(chunks) >= 2
    solar = [c for c in chunks if "Solar" in c.text]
    assert all("cafeteria" not in c.text for c in solar)


def test_semantic_chunker_does_not_split_paragraphs():
    emb = _Emb()
    doc = _long_doc()
    chunks = SemanticChunker(emb.embed_uncached, chunk_size=2000, breakpoint_percentile=50).chunk(doc)
    paragraphs = [b.text for b in doc.blocks if b.kind == "paragraph"]
    for p in paragraphs:
        assert any(p in c.text for c in chunks)


def test_invalid_overlap():
    with pytest.raises(ValueError):
        get_chunker("recursive", 100, 100)


def test_semantic_embeddings_normalised():
    v = FakeEmbeddings(64).embed_array(["hello world", "another text"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)
