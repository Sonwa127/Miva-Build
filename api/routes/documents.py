"""FastAPI router for PDF upload, indexing, and document retrieval."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Response, status
from fastapi.responses import FileResponse

from archive import analytics, config, courses, course_weeks, ingest, registry
from archive.store import VectorStore
from ..deps import get_store
from ..models import ChunkResponse, DocumentPlacementUpdate, DocumentResponse, PageContentResponse
from ..auth import require_admin

router = APIRouter(prefix="/api/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def upload_document(
    file: UploadFile = File(...),
    course: str = Form(""),
    force: bool = Form(False),
    ocr: bool = Form(False),
    week: int | None = Form(None, ge=0, le=52),
    store: VectorStore = Depends(get_store),
):
    """Upload and ingest a PDF lecture or course reading."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files (.pdf) are supported.",
        )

    course = " ".join(course.split())
    course_record = courses.get_course(course) if course else None
    if not course_record:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select an existing course before uploading a document.",
        )
    course = course_record.code
    try:
        course_weeks.validate_placement(course, week or 0)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    upload_dir = config.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Browsers normally send only a basename, but never trust a client-supplied path.
    safe_filename = Path(file.filename or "upload.pdf").name
    temp_path = upload_dir / f".{uuid.uuid4().hex}.upload"

    size = 0
    try:
        with open(temp_path, "wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(413, "PDF uploads must be no larger than 50 MB.")
                buffer.write(chunk)
        import fitz
        with fitz.open(temp_path, filetype="pdf") as pdf:
            if pdf.needs_pass or len(pdf) == 0:
                raise ValueError("Use a non-empty PDF without password protection.")
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(422, "Upload a valid, non-empty PDF without password protection.") from error

    sha = ingest.file_sha256(temp_path)
    existing = registry.get_by_hash(sha)
    if existing and existing.course != course:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This PDF is already indexed under course '{existing.course}'.",
        )

    if existing and week is not None and week != existing.week:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(409, "This PDF is already published. Use Edit placement in the PDF list to move it to another week.")

    if existing and Path(existing.path).is_file():
        temp_path.unlink(missing_ok=True)
        stored_path = Path(existing.path)
    else:
        document_dir = upload_dir / sha[:12]
        document_dir.mkdir(parents=True, exist_ok=True)
        stored_path = document_dir / safe_filename
        temp_path.replace(stored_path)

    res = ingest.ingest_pdf(stored_path, store, course=course, force=force, enable_ocr=ocr)

    if res.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {res.detail}",
        )
    if res.status == "empty":
        # A scanned PDF is still a useful reading. Publish its original pages
        # even when it cannot yet contribute text to the search index.
        with fitz.open(stored_path) as pdf:
            registry.add(registry.DocRecord(
                doc_id=sha[:12], sha256=sha, title=pdf.metadata.get("title") or stored_path.stem,
                course=course, filename=stored_path.name, path=str(stored_path.resolve()),
                page_count=len(pdf), chunk_count=0, ingested_at=registry.now_iso(),
                week=existing.week if existing else (week or 0),
            ))

    rec = registry.get_by_hash(sha)
    if not rec:
        raise HTTPException(status_code=500, detail="Could not register document.")
    if not existing and week:
        rec = registry.set_week(rec.doc_id, week)

    # Log to activity feed
    analytics.log_activity("document", "Indexed Document", f"{rec.title} • {rec.page_count} pages", rec.course)

    return DocumentResponse(
        doc_id=rec.doc_id,
        sha256=rec.sha256,
        title=rec.title,
        course=rec.course,
        filename=rec.filename,
        path=rec.path,
        page_count=rec.page_count,
        chunk_count=rec.chunk_count,
        ingested_at=rec.ingested_at,
        week=rec.week,
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(course: str | None = None, week: int | None = Query(None, ge=0, le=52)):
    """List all ingested course documents."""
    docs = registry.list_all(course, week)
    return [
        DocumentResponse(
            doc_id=d.doc_id,
            sha256=d.sha256,
            title=d.title,
            course=d.course,
            filename=d.filename,
            path=d.path,
            page_count=d.page_count,
            chunk_count=d.chunk_count,
            ingested_at=d.ingested_at,
            week=d.week,
        )
        for d in docs
    ]


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str):
    """Get metadata for a single document."""
    d = registry.get(doc_id)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentResponse(
        doc_id=d.doc_id,
        sha256=d.sha256,
        title=d.title,
        course=d.course,
        filename=d.filename,
        path=d.path,
        page_count=d.page_count,
        chunk_count=d.chunk_count,
        ingested_at=d.ingested_at,
        week=d.week,
    )


@router.patch("/{doc_id}/placement", response_model=DocumentResponse, dependencies=[Depends(require_admin)])
def update_document_placement(doc_id: str, payload: DocumentPlacementUpdate):
    document = registry.get(doc_id)
    if not document:
        raise HTTPException(404, "Document not found.")
    try:
        course_weeks.validate_placement(document.course, payload.week)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return DocumentResponse(**asdict(registry.set_week(doc_id, payload.week)))


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_document(doc_id: str, store: VectorStore = Depends(get_store)):
    """Delete a document from vector store and registry."""
    store.delete_doc(doc_id)
    ok = registry.remove(doc_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return None


@router.get("/{doc_id}/pages/{page}", response_model=PageContentResponse)
async def get_document_page(
    doc_id: str,
    page: int,
    store: VectorStore = Depends(get_store),
):
    """Fetch text chunks for a specific slide or page in reading view."""
    document = registry.get(doc_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if page < 1 or page > max(document.page_count, 1):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page must be between 1 and {document.page_count}.",
        )
    chunks = store.get_page(doc_id, page)

    return PageContentResponse(
        doc_id=doc_id,
        page=page,
        content=chunks,
        total_pages=document.page_count,
    )


@router.get("/{doc_id}/chunks", response_model=list[ChunkResponse])
async def list_document_chunks(
    doc_id: str,
    page: int | None = None,
    store: VectorStore = Depends(get_store),
):
    """List stored chunks of a document, optionally for a specific page."""
    rows = store.list_chunks(doc_id, page)
    return [
        ChunkResponse(page=r[0], index=r[1], chapter=r[2], text=r[3])
        for r in rows
    ]


def original_document(doc_id: str):
    document = registry.get(doc_id)
    if not document:
        raise HTTPException(404, "Document not found.")
    path = Path(document.path).resolve()
    if not path.is_file():
        raise HTTPException(404, "The original PDF is unavailable. Ask the administrator to upload it again.")
    return document, path


@router.get("/{doc_id}/file")
def get_original_pdf(doc_id: str, download: bool = False):
    document, path = original_document(doc_id)
    return FileResponse(path, media_type="application/pdf", filename=document.filename,
                        content_disposition_type="attachment" if download else "inline",
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{doc_id}/pages/{page}/image")
def get_page_image(doc_id: str, page: int):
    """Render the original PDF page, preserving fonts, equations, tables and images."""
    import fitz

    document, path = original_document(doc_id)
    if page < 1 or page > document.page_count:
        raise HTTPException(404, "Page not found.")
    try:
        with fitz.open(path) as pdf:
            if page > len(pdf):
                raise HTTPException(404, "Page not found in the original PDF.")
            original = pdf[page - 1]
            # Keep images readable on retina displays while bounding rendering memory.
            area = max(1, original.rect.width * original.rect.height)
            scale = min(1800 / max(1, original.rect.width), (5_000_000 / area) ** 0.5)
            image = original.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise HTTPException(422, "The PDF page could not be displayed. Try downloading the original.") from error
    return Response(image, media_type="image/png", headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})
