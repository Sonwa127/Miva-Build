"""Concept glossary extraction and indexing grounded in course materials."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
    id            TEXT PRIMARY KEY,
    course_id     TEXT NOT NULL DEFAULT '',
    doc_id        TEXT NOT NULL DEFAULT '',
    term          TEXT NOT NULL,
    definition    TEXT NOT NULL,
    source_page   INTEGER NOT NULL DEFAULT 1,
    related_terms TEXT NOT NULL DEFAULT '[]',  -- JSON list of strings
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_glossary_term ON glossary(term);
CREATE INDEX IF NOT EXISTS idx_glossary_course ON glossary(course_id);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class GlossaryEntry:
    id: str
    course_id: str
    doc_id: str
    term: str
    definition: str
    source_page: int
    related_terms: list[str] = field(default_factory=list)
    created_at: str = ""


@contextmanager
def get_db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_glossary(
    doc_id: str,
    store,
    llm,
    course_id: str = "",
    max_chunks: int = 25,
) -> list[GlossaryEntry]:
    raw_chunks = store.list_chunks(doc_id)
    if not raw_chunks:
        return []

    context_str = "\n\n".join(
        f"[Page {r[0]}] {r[3][:450]}" for r in raw_chunks[:max_chunks]
    )

    system_prompt = (
        "You are an academic lexicographer. Extract technical concepts, algorithms, data structures, and theorems "
        "defined in the course lecture notes.\n"
        "Return ONLY a valid JSON array of objects with keys:\n"
        "- 'term': Exact academic term or algorithmic name\n"
        "- 'definition': Concise, mathematically/conceptually rigorous definition according to the text\n"
        "- 'source_page': Integer page number where defined\n"
        "- 'related_terms': Array of 2-4 related concept strings\n"
        "Return ONLY the JSON array without code fences."
    )

    user_prompt = f"LECTURE EXCERPTS:\n\n{context_str}"

    try:
        reply = llm.complete(system_prompt, user_prompt, temperature=0.1, max_tokens=2000)
        cleaned = reply.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        items = json.loads(cleaned)
    except Exception:
        items = []

    entries: list[GlossaryEntry] = []
    now = now_iso()

    with get_db() as c:
        for item in items:
            term = str(item.get("term", "")).strip()
            definition = str(item.get("definition", "")).strip()
            if not term or not definition:
                continue
            page = int(item.get("source_page", 1))
            related = item.get("related_terms", [])
            gid = f"gl_{uuid.uuid4().hex[:10]}"

            c.execute(
                """INSERT INTO glossary (id, course_id, doc_id, term, definition, source_page, related_terms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (gid, course_id, doc_id, term, definition, page, json.dumps(related), now),
            )
            entries.append(GlossaryEntry(
                id=gid,
                course_id=course_id,
                doc_id=doc_id,
                term=term,
                definition=definition,
                source_page=page,
                related_terms=related,
                created_at=now,
            ))

    return entries


def get_glossary(course_id: str | None = None, doc_id: str | None = None) -> list[GlossaryEntry]:
    query = "SELECT * FROM glossary"
    filters = []
    params = []
    if course_id:
        filters.append("course_id = ?")
        params.append(course_id)
    if doc_id:
        filters.append("doc_id = ?")
        params.append(doc_id)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY term ASC"

    with get_db() as c:
        rows = c.execute(query, params).fetchall()

    return [
        GlossaryEntry(
            id=r["id"],
            course_id=r["course_id"],
            doc_id=r["doc_id"],
            term=r["term"],
            definition=r["definition"],
            source_page=r["source_page"],
            related_terms=json.loads(r["related_terms"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def search_glossary(query_str: str, course_id: str | None = None) -> list[GlossaryEntry]:
    sql = "SELECT * FROM glossary WHERE (term LIKE ? OR definition LIKE ?)"
    params = [f"%{query_str}%", f"%{query_str}%"]
    if course_id:
        sql += " AND course_id = ?"
        params.append(course_id)
    sql += " ORDER BY term ASC"

    with get_db() as c:
        rows = c.execute(sql, params).fetchall()

    return [
        GlossaryEntry(
            id=r["id"],
            course_id=r["course_id"],
            doc_id=r["doc_id"],
            term=r["term"],
            definition=r["definition"],
            source_page=r["source_page"],
            related_terms=json.loads(r["related_terms"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
