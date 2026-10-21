import os
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeEmbedder:
    """Deterministic bag-of-words embedder so tests need no model download."""
    DIM = 64

    def __call__(self, input):
        out = []
        for text in input:
            v = [0.0] * self.DIM
            for w in text.lower().split():
                v[hash(w.strip(".,")) % self.DIM] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out

    def name(self):
        return "fake"

    def embed_query(self, input):
        return self(input)

    def embed_documents(self, input):
        return self(input)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    from archive import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "data" / "chroma")
    monkeypatch.setattr(config, "REGISTRY_DB", tmp_path / "data" / "registry.sqlite")
    return tmp_path


def make_pdf(path: Path, pages: list[str]):
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 780), text, fontsize=11)
    doc.save(path)
    doc.close()


def test_ingest_search_dedupe_remove(env):
    from archive import registry
    from archive.ingest import ingest_pdf
    from archive.store import VectorStore

    pdf = env / "ml.pdf"
    make_pdf(pdf, [
        "Gradient descent is an optimization algorithm that minimizes a loss function by "
        "moving parameters against the gradient. " * 3,
        "Photosynthesis converts light energy into chemical energy inside chloroplasts. " * 3,
    ])
    store = VectorStore(embedding_function=FakeEmbedder())

    res = ingest_pdf(pdf, store, course="Demo")
    assert res.status == "ingested" and res.pages == 2 and res.chunks >= 2

    hits = store.search("gradient descent minimizes loss", k=2)
    assert hits[0].page == 1
    assert hits[0].citation.endswith("p. 1]")

    again = ingest_pdf(pdf, store, course="Demo")
    assert again.status == "skipped"
    count_before = store.count()
    registry.set_week(res.doc_id, 3)
    ingest_pdf(pdf, store, course="Demo", force=True)
    assert store.count() == count_before          # force re-ingest does not duplicate
    assert registry.get(res.doc_id).week == 3

    # A stale registry must not make ingestion skip a missing vector index.
    store.delete_doc(res.doc_id)
    repaired = ingest_pdf(pdf, store, course="Demo")
    assert repaired.status == "ingested"
    assert store.count_doc(res.doc_id) == repaired.chunks
    assert registry.get(res.doc_id).week == 3

    assert [d.doc_id for d in registry.list_all()] == [res.doc_id]
    store.delete_doc(res.doc_id)
    assert registry.remove(res.doc_id)
    assert store.count() == 0


def test_offline_search_finds_exact_terms_and_rejects_unrelated_topic(env):
    from archive.chunker import Chunk
    from archive.store import VectorStore

    store = VectorStore()
    store.add_chunks("physics", "Mechanics", "PHY101", [
        Chunk(2, 0, "Newton's second law states that force equals mass times acceleration.", ""),
        Chunk(3, 0, "Velocity describes how an object's position changes over time.", ""),
    ])

    relevant = store.search("State Newton's second law", course="PHY101", k=1)
    unrelated = store.search("Explain quantum superposition in nuclear physics", course="PHY101", k=1)

    assert relevant[0].page == 2 and relevant[0].score >= 0.30
    assert unrelated[0].score < 0.30


def test_blank_pdf_reports_empty(env):
    from archive.ingest import ingest_pdf
    from archive.store import VectorStore

    pdf = env / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf)
    doc.close()
    res = ingest_pdf(pdf, VectorStore(embedding_function=FakeEmbedder()))
    assert res.status == "empty"
