"""PDF parsing with PyMuPDF: per-page text, chapter mapping, optional OCR."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from . import config


@dataclass
class Page:
    number: int          # 1-based page number as printed in a PDF viewer
    text: str
    chapter: str         # nearest outline heading at or before this page, or ""
    ocr_used: bool = False


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _chapter_map(doc: "fitz.Document") -> dict[int, str]:
    """Map each page number to the latest top-level outline entry that starts at or before it."""
    toc = doc.get_toc(simple=True)  # [level, title, page]
    starts: dict[int, str] = {}
    for level, title, page in toc:
        if level <= 2 and page >= 1:
            starts.setdefault(page, title.strip())
    mapping: dict[int, str] = {}
    current = ""
    for n in range(1, doc.page_count + 1):
        current = starts.get(n, current)
        mapping[n] = current
    return mapping


def _page_text(page: "fitz.Page", enable_ocr: bool) -> tuple[str, bool]:
    text = page.get_text("text").strip()
    if len(text) >= config.OCR_MIN_CHARS or not enable_ocr:
        return text, False
    try:
        tp = page.get_textpage_ocr(full=True)
        return page.get_text("text", textpage=tp).strip(), True
    except Exception:
        # Tesseract missing or OCR failed: keep whatever text we have.
        return text, False


def parse_pdf(path: Path, enable_ocr: bool | None = None) -> tuple[dict, list[Page]]:
    """Return (metadata, pages). Empty pages are kept out of the result."""
    enable_ocr = config.ENABLE_OCR if enable_ocr is None else enable_ocr
    with fitz.open(path) as doc:
        meta = {
            "title": (doc.metadata or {}).get("title") or path.stem,
            "page_count": doc.page_count,
        }
        chapters = _chapter_map(doc)
        pages: list[Page] = []
        for i in range(doc.page_count):
            text, used = _page_text(doc[i], enable_ocr)
            if text:
                pages.append(Page(i + 1, text, chapters.get(i + 1, ""), used))
    return meta, pages
