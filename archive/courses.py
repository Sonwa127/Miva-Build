"""Course management with SQLite database."""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    instructor  TEXT NOT NULL DEFAULT '',
    term        TEXT NOT NULL DEFAULT '',
    schedule    TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    credits     REAL NOT NULL DEFAULT 0.0,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class Course:
    id: str
    code: str
    name: str
    instructor: str
    term: str
    schedule: str
    description: str
    credits: float
    status: str
    created_at: str


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


def create_course(
    code: str,
    name: str,
    instructor: str = "",
    term: str = "",
    schedule: str = "",
    description: str = "",
    credits: float = 0.0,
    status: str = "active",
) -> Course:
    course_id = f"c_{uuid.uuid4().hex[:10]}"
    created = now_iso()
    with get_db() as c:
        c.execute(
            """INSERT INTO courses (id, code, name, instructor, term, schedule, description, credits, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (course_id, code.strip(), name.strip(), instructor.strip(), term.strip(),
             schedule.strip(), description.strip(), float(credits), status.strip(), created)
        )
    return Course(
        id=course_id,
        code=code.strip(),
        name=name.strip(),
        instructor=instructor.strip(),
        term=term.strip(),
        schedule=schedule.strip(),
        description=description.strip(),
        credits=float(credits),
        status=status.strip(),
        created_at=created,
    )


def get_course(course_id: str) -> Course | None:
    with get_db() as c:
        row = c.execute("SELECT * FROM courses WHERE id = ? OR code = ?", (course_id, course_id)).fetchone()
    return Course(**row) if row else None


def list_courses(status: str | None = None) -> list[Course]:
    with get_db() as c:
        if status:
            rows = c.execute("SELECT * FROM courses WHERE status = ? ORDER BY code ASC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM courses ORDER BY code ASC").fetchall()
    return [Course(**r) for r in rows]


def update_course(course_id: str, **fields) -> Course | None:
    allowed = {"code", "name", "instructor", "term", "schedule", "description", "credits", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_course(course_id)

    set_clauses = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [course_id]

    with get_db() as c:
        c.execute(f"UPDATE courses SET {set_clauses} WHERE id = ?", values)
    return get_course(course_id)


def delete_course(course_id: str) -> bool:
    with get_db() as c:
        cur = c.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        return cur.rowcount > 0


def get_course_stats(course_id: str) -> dict:
    course = get_course(course_id)
    if not course:
        return {"doc_count": 0, "page_count": 0, "chunk_count": 0, "flashcard_count": 0, "quiz_count": 0}

    # Query registry.sqlite for document statistics
    from . import registry
    docs = registry.list_all(course.code)
    doc_count = len(docs)
    page_count = sum(d.page_count for d in docs)
    chunk_count = sum(d.chunk_count for d in docs)

    # Flashcard count & quiz count from app.sqlite
    with get_db() as c:
        # Check if tables exist before querying
        fc_table = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flashcards'").fetchone()
        fc_count = 0
        if fc_table:
            row = c.execute("SELECT count(*) as cnt FROM flashcards WHERE course_id = ?", (course.code,)).fetchone()
            fc_count = row["cnt"] if row else 0

        quiz_table = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quizzes'").fetchone()
        quiz_count = 0
        if quiz_table:
            row = c.execute("SELECT count(*) as cnt FROM quizzes WHERE course_id = ?", (course.code,)).fetchone()
            quiz_count = row["cnt"] if row else 0

    return {
        "doc_count": doc_count,
        "page_count": page_count,
        "chunk_count": chunk_count,
        "flashcard_count": fc_count,
        "quiz_count": quiz_count,
    }
