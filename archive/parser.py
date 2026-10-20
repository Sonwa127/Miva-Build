"""PDF parsing with PyMuPDF: per-page text, chapter mapping, optional OCR."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_plus

import pymupdf as fitz  # PyMuPDF (the old "import fitz" name is deprecated)

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


_EXT_AT_END = re.compile(r"\s*\.(docx?|pptx?|xlsx?|odt|pdf)\s*$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")


def _clean_title(title: str) -> str:
    """Decode URL-style filenames and drop leftover document extensions."""
    decoded = unquote_plus(title).strip()
    return _EXT_AT_END.sub("", decoded).strip() or decoded


def _norm(line: str) -> str:
    """Normalise a line so 'Page 3' and 'Page 4' count as the same running footer."""
    return _DIGITS.sub("#", " ".join(line.split())).lower()


def strip_running_headers(pages: list[Page], edge: int = 3, min_share: float = 0.5,
                          min_pages: int = 4) -> list[Page]:
    """Remove lines that repeat at the top or bottom of at least half the pages
    (running headers, footers, page numbers). Only the first and last `edge` lines
    of each page are touched, so real content in the middle is never removed."""
    if len(pages) < min_pages:
        return pages

    def edge_positions(lines: list[str]) -> set[int]:
        nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
        return set(nonempty[:edge]) | set(nonempty[-edge:])

    counts: dict[str, int] = {}
    for p in pages:
        lines = p.text.splitlines()
        for key in {_norm(lines[i]) for i in edge_positions(lines)}:
            counts[key] = counts.get(key, 0) + 1

    threshold = max(3, int(len(pages) * min_share))
    repeated = {k for k, c in counts.items() if c >= threshold and k}
    if not repeated:
        return pages

    cleaned: list[Page] = []
    for p in pages:
        lines = p.text.splitlines()
        edges = edge_positions(lines)
        kept = [ln for i, ln in enumerate(lines) if not (i in edges and _norm(ln) in repeated)]
        text = "\n".join(kept).strip()
        if text:                                    # a page that was only a header disappears
            cleaned.append(Page(p.number, text, p.chapter, p.ocr_used))
    return cleaned


def parse_pdf(path: Path, enable_ocr: bool | None = None) -> tuple[dict, list[Page]]:
    """Return (metadata, pages). Empty pages are kept out of the result."""
    enable_ocr = config.ENABLE_OCR if enable_ocr is None else enable_ocr
    with fitz.open(path) as doc:
        meta = {
            "title": _clean_title((doc.metadata or {}).get("title") or path.stem),
            "page_count": doc.page_count,
        }
        chapters = _chapter_map(doc)
        pages: list[Page] = []
        for i in range(doc.page_count):
            text, used = _page_text(doc[i], enable_ocr)
            if text:
                pages.append(Page(i + 1, text, chapters.get(i + 1, ""), used))
    return meta, strip_running_headers(pages)
