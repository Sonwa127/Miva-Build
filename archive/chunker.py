"""Page-aware chunking. Chunks never span pages so citations stay exact."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .parser import Page


@dataclass
class Chunk:
    page: int
    index: int           # position of the chunk within its page
    text: str
    chapter: str


_WS = re.compile(r"[ \t]+")


def _clean(text: str) -> str:
    text = text.replace("­", "")                    # soft hyphens
    text = re.sub(r"-\n(?=[a-z])", "", text)             # re-join hyphenated line breaks
    text = _WS.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_paragraph(par: str, size: int) -> list[str]:
    """Break an oversized paragraph on sentence boundaries, hard-cutting as a last resort."""
    sentences = re.split(r"(?<=[.!?])\s+", par)
    out, buf = [], ""
    for s in sentences:
        while len(s) > size:                              # one giant "sentence"
            if buf:
                out.append(buf)
                buf = ""
            out.append(s[:size])
            s = s[size:]
        if len(buf) + len(s) + 1 > size and buf:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    return out


def chunk_page(page: Page, size: int | None = None, overlap: int | None = None) -> list[Chunk]:
    size = size or config.CHUNK_CHARS
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap
    text = _clean(page.text)
    if not text:
        return []

    pieces: list[str] = []
    for par in re.split(r"\n\s*\n", text):
        par = par.replace("\n", " ").strip()
        if par:
            pieces.extend(_split_paragraph(par, size) if len(par) > size else [par])

    chunks_text: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 2 > size:
            chunks_text.append(buf)
            tail = buf[-overlap:] if overlap else ""
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail   # start on a word
            buf = f"{tail} {piece}".strip()
        else:
            buf = f"{buf}\n\n{piece}".strip() if buf else piece
    if buf:
        if chunks_text and len(buf) < config.MIN_CHUNK_CHARS:
            chunks_text[-1] = f"{chunks_text[-1]}\n\n{buf}"      # fold a tiny tail into the previous chunk
        else:
            chunks_text.append(buf)

    return [Chunk(page.number, i, t, page.chapter) for i, t in enumerate(chunks_text)]


def chunk_pages(pages: list[Page]) -> list[Chunk]:
    out: list[Chunk] = []
    for p in pages:
        out.extend(chunk_page(p))
    return out
