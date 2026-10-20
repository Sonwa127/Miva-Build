"""Analytics and curriculum pain-point telemetry."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    confidence REAL NOT NULL,
    cited      BOOLEAN NOT NULL,
    course     TEXT NOT NULL DEFAULT '',
    doc_id     TEXT NOT NULL DEFAULT '',
    timestamp  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_log_id INTEGER,
    rating       INTEGER NOT NULL, -- 1 (upvote/helpful) or -1 (downvote/unhelpful)
    comment      TEXT NOT NULL DEFAULT '',
    timestamp    TEXT NOT NULL,
    FOREIGN KEY(query_log_id) REFERENCES query_log(id)
);

CREATE TABLE IF NOT EXISTS topic_frequency (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    course       TEXT NOT NULL DEFAULT '',
    count        INTEGER NOT NULL DEFAULT 1,
    last_queried TEXT NOT NULL,
    UNIQUE(topic, course)
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL, -- 'quiz', 'flashcard', 'document', 'qa', 'summary'
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    course_code TEXT NOT NULL DEFAULT '',
    timestamp   TEXT NOT NULL
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class QueryLogEntry:
    id: int
    question: str
    answer: str
    confidence: float
    cited: bool
    course: str
    doc_id: str
    timestamp: str


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


def log_query(
    question: str,
    answer: str,
    confidence: float,
    cited: bool,
    course: str = "",
    doc_id: str = "",
) -> int:
    now = now_iso()
    with get_db() as c:
        cur = c.execute(
            """INSERT INTO query_log (question, answer, confidence, cited, course, doc_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (question, answer, float(confidence), bool(cited), course, doc_id, now),
        )
        log_id = cur.lastrowid

        # Also log to activity feed
        short_q = (question[:45] + "...") if len(question) > 45 else question
        c.execute(
            """INSERT INTO activity_log (type, title, detail, course_code, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("qa", f"Asked AI Assistant", f'"{short_q}"', course, now),
        )

        # Update topic frequency (simple unigrams/bigrams heuristic)
        words = [w.lower() for w in question.split() if len(w) > 3 and w.lower() not in {"what", "when", "where", "which", "does", "explain", "about", "their", "there"}]
        for w in words[:3]:
            c.execute(
                """INSERT INTO topic_frequency (topic, course, count, last_queried)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(topic, course) DO UPDATE SET count = count + 1, last_queried = ?""",
                (w, course, now, now),
            )

    return log_id or 0


def log_feedback(query_log_id: int, rating: int, comment: str = "") -> None:
    with get_db() as c:
        c.execute(
            """INSERT INTO feedback (query_log_id, rating, comment, timestamp)
               VALUES (?, ?, ?, ?)""",
            (query_log_id, rating, comment, now_iso()),
        )


def log_activity(activity_type: str, title: str, detail: str = "", course_code: str = "") -> None:
    with get_db() as c:
        c.execute(
            """INSERT INTO activity_log (type, title, detail, course_code, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (activity_type, title, detail, course_code, now_iso()),
        )


def get_low_confidence_queries(threshold: float = 0.50, limit: int = 20) -> list[dict]:
    with get_db() as c:
        rows = c.execute(
            """SELECT q.*, f.rating as feedback_rating, f.comment as feedback_comment
               FROM query_log q
               LEFT JOIN feedback f ON q.id = f.query_log_id
               WHERE q.confidence < ? OR q.cited = 0 OR f.rating < 0
               ORDER BY q.timestamp DESC LIMIT ?""",
            (threshold, limit),
        ).fetchall()

    return [dict(r) for r in rows]


def get_frequent_topics(course: str | None = None, limit: int = 15) -> list[dict]:
    with get_db() as c:
        if course:
            rows = c.execute(
                "SELECT topic, course, count, last_queried FROM topic_frequency WHERE course = ? ORDER BY count DESC LIMIT ?",
                (course, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT topic, course, sum(count) as count, max(last_queried) as last_queried FROM topic_frequency GROUP BY topic ORDER BY count DESC LIMIT ?",
                (limit,),
            ).fetchall()

    return [dict(r) for r in rows]


def get_study_stats(course: str | None = None) -> dict:
    with get_db() as c:
        total_q = c.execute("SELECT count(*) as cnt, avg(confidence) as avg_conf FROM query_log").fetchone()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_q = c.execute("SELECT count(*) as cnt FROM query_log WHERE timestamp LIKE ?", (f"{today}%",)).fetchone()
        # Calculate real active days
        streak_row = c.execute("SELECT count(DISTINCT substr(timestamp, 1, 10)) as days FROM activity_log").fetchone()
        streak_days = streak_row["days"] if streak_row else 0

    avg_conf = round((total_q["avg_conf"] or 0.0) * 100, 1) if total_q and total_q["avg_conf"] else 0.0
    queries_count = total_q["cnt"] if total_q else 0
    study_hours = round(queries_count * 0.1, 1)

    return {
        "total_queries": queries_count,
        "avg_confidence": avg_conf,
        "queries_today": today_q["cnt"] if today_q else 0,
        "streak_days": streak_days,
        "study_hours": study_hours,
    }


def get_activity_feed(limit: int = 10) -> list[dict]:
    with get_db() as c:
        rows = c.execute(
            "SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()

    return [dict(r) for r in rows]
