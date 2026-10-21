"""SQLite registry of ingested documents (dedupe by content hash, list, remove)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config
from .schema import ensure_week_column

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    course      TEXT NOT NULL DEFAULT '',
    filename    TEXT NOT NULL,
    path        TEXT NOT NULL,
    page_count  INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    ingested_at TEXT NOT NULL
);
"""


@dataclass
class DocRecord:
    doc_id: str
    sha256: str
    title: str
    course: str
    filename: str
    path: str
    page_count: int
    chunk_count: int
    ingested_at: str
    week: int = 0


@contextmanager
def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.REGISTRY_DB)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    ensure_week_column(con, "documents")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def get_by_hash(sha256: str) -> DocRecord | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
    return DocRecord(**row) if row else None


def get(doc_id: str) -> DocRecord | None:
    """Return a document by its public ID."""
    with _conn() as c:
        row = c.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return DocRecord(**row) if row else None


def add(rec: DocRecord) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO documents (doc_id, sha256, title, course, filename, path, page_count, chunk_count, ingested_at, week) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rec.doc_id, rec.sha256, rec.title, rec.course, rec.filename,
             rec.path, rec.page_count, rec.chunk_count, rec.ingested_at, rec.week),
        )


def list_all(course: str | None = None, week: int | None = None) -> list[DocRecord]:
    with _conn() as c:
        filters, values = [], []
        if course:
            filters.append("course = ?")
            values.append(course)
        if week is not None:
            filters.append("week = ?")
            values.append(week)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        rows = c.execute("SELECT * FROM documents" + where + " ORDER BY course, week, title", values).fetchall()
    return [DocRecord(**r) for r in rows]


def set_week(doc_id: str, week: int) -> DocRecord | None:
    with _conn() as c:
        c.execute("UPDATE documents SET week = ? WHERE doc_id = ?", (week, doc_id))
    return get(doc_id)


def remove(doc_id: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        return cur.rowcount > 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
