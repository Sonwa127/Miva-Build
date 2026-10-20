"""Ingestion pipeline: PDF -> pages -> chunks -> vector store + registry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import registry
from .chunker import chunk_pages
from .parser import file_sha256, parse_pdf
from .store import VectorStore


@dataclass
class IngestResult:
    path: Path
    status: str          # "ingested" | "skipped" | "empty" | "failed"
    doc_id: str = ""
    pages: int = 0
    chunks: int = 0
    detail: str = ""


def ingest_pdf(path: Path, store: VectorStore, course: str = "",
               force: bool = False, enable_ocr: bool | None = None) -> IngestResult:
    path = Path(path)
    try:
        sha = file_sha256(path)
        existing = registry.get_by_hash(sha)
        if existing and not force:
            stored_chunks = store.count_doc(existing.doc_id)
            if stored_chunks == existing.chunk_count and stored_chunks > 0:
                return IngestResult(
                    path, "skipped", existing.doc_id,
                    existing.page_count, existing.chunk_count,
                    detail="already ingested and index verified",
                )

        doc_id = sha[:12]
        meta, pages = parse_pdf(path, enable_ocr)
        chunks = chunk_pages(pages)
        if not chunks:
            return IngestResult(path, "empty", doc_id,
                                detail="no extractable text (scanned? try --ocr)")

        # Parse and chunk successfully before replacing the old vector entries.
        # This avoids destroying a working index when PDF parsing fails.
        if existing or force:
            store.delete_doc(doc_id)
        store.add_chunks(doc_id, meta["title"], course, chunks)
        registry.add(registry.DocRecord(
            doc_id=doc_id, sha256=sha, title=meta["title"], course=course,
            filename=path.name, path=str(path.resolve()),
            page_count=meta["page_count"], chunk_count=len(chunks),
            ingested_at=registry.now_iso(),
        ))
        return IngestResult(path, "ingested", doc_id, meta["page_count"], len(chunks))
    except Exception as e:  # one bad PDF must not stop a batch
        return IngestResult(path, "failed", detail=f"{type(e).__name__}: {e}")


def ingest_path(target: Path, store: VectorStore, course: str = "",
                force: bool = False, enable_ocr: bool | None = None) -> list[IngestResult]:
    target = Path(target)
    files = sorted(target.rglob("*.pdf")) if target.is_dir() else [target]
    return [ingest_pdf(f, store, course, force, enable_ocr) for f in files]
