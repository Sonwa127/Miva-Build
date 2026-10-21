"""Flashcard generation and SM-2 spaced repetition scheduling."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config
from .jsonparse import parse_json_list

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flashcards (
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL DEFAULT '',
    doc_id      TEXT NOT NULL DEFAULT '',
    page        INTEGER NOT NULL DEFAULT 1,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    difficulty  TEXT NOT NULL DEFAULT 'mechanics',
    tags        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS card_reviews (
    card_id       TEXT PRIMARY KEY,
    ease_factor   REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    next_review   TEXT NOT NULL,
    last_review   TEXT,
    rating        INTEGER DEFAULT 0,
    FOREIGN KEY(card_id) REFERENCES flashcards(id) ON DELETE CASCADE
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class Flashcard:
    id: str
    course_id: str
    doc_id: str
    page: int
    question: str
    answer: str
    source_text: str
    difficulty: str
    tags: str
    created_at: str
    ease_factor: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    next_review: str = ""
    last_review: str | None = None


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


def _row_to_card(row: sqlite3.Row) -> Flashcard:
    return Flashcard(
        id=row["id"],
        course_id=row["course_id"],
        doc_id=row["doc_id"],
        page=row["page"],
        question=row["question"],
        answer=row["answer"],
        source_text=row["source_text"],
        difficulty=row["difficulty"],
        tags=row["tags"],
        created_at=row["created_at"],
        ease_factor=row["ease_factor"] if "ease_factor" in row.keys() and row["ease_factor"] is not None else 2.5,
        interval_days=row["interval_days"] if "interval_days" in row.keys() and row["interval_days"] is not None else 0,
        repetitions=row["repetitions"] if "repetitions" in row.keys() and row["repetitions"] is not None else 0,
        next_review=row["next_review"] if "next_review" in row.keys() and row["next_review"] is not None else row["created_at"],
        last_review=row["last_review"] if "last_review" in row.keys() else None,
    )


def generate_flashcards(
    doc_id: str,
    store,
    llm,
    course_id: str = "",
    topic: str = "",
    batch_size: int = 15,
    difficulty: str = "mechanics",
    include_citations: bool = True,
) -> list[Flashcard]:
    """Synthesize high-yield flashcard Q&As strictly grounded in the document chunks."""
    # Retrieve chunks for the document or topic
    if topic:
        hits = store.search(topic, k=min(batch_size * 2, 20), doc_id=doc_id)
        chunks_info = [{"page": h.page, "text": h.text, "title": h.title} for h in hits]
    else:
        raw_chunks = store.list_chunks(doc_id)
        if not raw_chunks:
            return []
        chunks_info = [{"page": r[0], "text": r[3], "title": doc_id} for r in raw_chunks[:30]]

    if not chunks_info:
        return []

    context_str = "\n\n".join(
        f"[Page {c['page']}] {c['text'][:400]}" for c in chunks_info[:15]
    )

    rigor_instructions = {
        "conceptual": "Focus on high-level definitions, core theorems, and primary conceptual distinctions.",
        "mechanics": "Focus on algorithmic tracing, step sequences, pointer changes, invariants, and state transitions.",
        "synthesis": "Focus on exam-level worst-case trade-offs, edge cases, comparative advantages, and structural proofs.",
    }.get(difficulty.lower(), "Focus on essential conceptual understanding and algorithmic mechanisms.")

    system_prompt = (
        "You are an expert university exam tutor. Generate active-recall flashcards based ONLY on the "
        "provided course material excerpts. Do NOT hallucinate concepts not explicitly stated in the excerpts.\n"
        f"Cognitive Rigor Target: {rigor_instructions}\n"
        f"Generate up to {batch_size} flashcards.\n"
        "Return a valid JSON array of objects with keys:\n"
        "- 'question': Clear, precise question or prompt\n"
        "- 'answer': Concise, comprehensive answer citing the exact mechanics\n"
        "- 'page': Integer page number where this concept is defined\n"
        "Return ONLY the JSON array without markdown formatting or code blocks."
    )

    user_prompt = f"COURSE MATERIAL EXCERPTS:\n\n{context_str}\n\nTOPIC FOCUS: {topic or 'Entire Document'}"

    raw_reply = llm.complete(system_prompt, user_prompt, temperature=0.2, max_tokens=3500)   # AI errors reach the admin
    items = parse_json_list(raw_reply)
    if not items:                                           # plain "Q: ... A: ..." style reply
        pattern = re.compile(r"Q(?:uestion)?:\s*(.*?)\nA(?:nswer)?:\s*(.*?)(?=\nQ:|\Z)", re.DOTALL | re.IGNORECASE)
        items = [{"question": m.group(1).strip(), "answer": m.group(2).strip(),
                  "page": chunks_info[0]["page"] if chunks_info else 1} for m in pattern.finditer(raw_reply)]

    created_cards = []
    now = now_iso()

    with get_db() as c:
        for item in items[:batch_size]:
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            if not q or not a:
                continue
            try:
                page = int(item.get("page", chunks_info[0]["page"] if chunks_info else 1))
            except (TypeError, ValueError):
                page = chunks_info[0]["page"] if chunks_info else 1
            cid = f"fc_{uuid.uuid4().hex[:10]}"

            c.execute(
                """INSERT INTO flashcards (id, course_id, doc_id, page, question, answer, source_text, difficulty, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cid, course_id, doc_id, page, q, a, f"Page {page}", difficulty, topic, now),
            )
            c.execute(
                """INSERT INTO card_reviews (card_id, ease_factor, interval_days, repetitions, next_review, last_review, rating)
                   VALUES (?, 2.5, 0, 0, ?, NULL, 0)""",
                (cid, now),
            )
            created_cards.append(Flashcard(
                id=cid,
                course_id=course_id,
                doc_id=doc_id,
                page=page,
                question=q,
                answer=a,
                source_text=f"Page {page}",
                difficulty=difficulty,
                tags=topic,
                created_at=now,
                ease_factor=2.5,
                interval_days=0,
                repetitions=0,
                next_review=now,
            ))

    return created_cards


def get_flashcards(course_id: str | None = None, doc_id: str | None = None, due_only: bool = False) -> list[Flashcard]:
    query = """
        SELECT f.*, r.ease_factor, r.interval_days, r.repetitions, r.next_review, r.last_review, r.rating
        FROM flashcards f
        LEFT JOIN card_reviews r ON f.id = r.card_id
    """
    filters = []
    params = []

    if course_id:
        filters.append("f.course_id = ?")
        params.append(course_id)
    if doc_id:
        filters.append("f.doc_id = ?")
        params.append(doc_id)
    if due_only:
        filters.append("r.next_review <= ?")
        params.append(now_iso())

    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY f.created_at DESC"

    with get_db() as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_card(r) for r in rows]


def get_due_cards(course_id: str | None = None) -> list[Flashcard]:
    return get_flashcards(course_id=course_id, due_only=True)


def review_card(card_id: str, rating: int) -> Flashcard | None:
    """Apply SM-2 spaced repetition algorithm based on user rating (0=Again, 3=Good, 5=Easy)."""
    now = datetime.now(timezone.utc)
    with get_db() as c:
        row = c.execute("SELECT * FROM card_reviews WHERE card_id = ?", (card_id,)).fetchone()
        if not row:
            return None

        ease_factor = row["ease_factor"]
        interval = row["interval_days"]
        reps = row["repetitions"]

        # SM-2 Algorithm update
        if rating < 3:
            reps = 0
            interval = 1
        else:
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = int(round(interval * ease_factor))
            reps += 1

        # Ease factor adjustment formula
        # EF' = EF + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
        ease_factor = ease_factor + (0.1 - (5 - rating) * (0.08 + (5 - rating) * 0.02))
        ease_factor = max(1.3, ease_factor)

        next_date = now + timedelta(days=interval)
        next_review_iso = next_date.isoformat(timespec="seconds")
        last_review_iso = now.isoformat(timespec="seconds")

        c.execute(
            """UPDATE card_reviews
               SET ease_factor = ?, interval_days = ?, repetitions = ?, next_review = ?, last_review = ?, rating = ?
               WHERE card_id = ?""",
            (ease_factor, interval, reps, next_review_iso, last_review_iso, rating, card_id),
        )

    cards = get_flashcards()
    for card in cards:
        if card.id == card_id:
            return card
    return None


def get_deck_stats(course_id: str | None = None) -> dict:
    with get_db() as c:
        where = "WHERE f.course_id = ?" if course_id else ""
        params = (course_id,) if course_id else ()

        sql = f"""
            SELECT
                count(*) as total,
                sum(case when r.repetitions = 0 then 1 else 0 end) as new_count,
                sum(case when r.repetitions > 0 and r.interval_days < 21 then 1 else 0 end) as learning_count,
                sum(case when r.interval_days >= 21 then 1 else 0 end) as mature_count,
                sum(case when r.next_review <= '{now_iso()}' then 1 else 0 end) as due_today
            FROM flashcards f
            LEFT JOIN card_reviews r ON f.id = r.card_id
            {where}
        """
        row = c.execute(sql, params).fetchone()
        if not row or row["total"] == 0:
            return {"total": 0, "new": 0, "learning": 0, "mature": 0, "due_today": 0, "retention_rate": 0.0}

        total = row["total"] or 0
        mature = row["mature_count"] or 0
        learning = row["learning_count"] or 0
        due = row["due_today"] or 0
        new_cnt = row["new_count"] or 0

        retention = round(((mature + (learning * 0.5)) / max(total, 1)) * 100, 1)

        return {
            "total": total,
            "new": new_cnt,
            "learning": learning,
            "mature": mature,
            "due_today": due,
            "retention_rate": retention,
        }


def export_anki(course_id: str | None = None) -> str:
    """Generate tab-separated format for direct Anki import."""
    cards = get_flashcards(course_id=course_id)
    lines = ["#separator:tab", "#html:true", "#tags column:3"]
    for c in cards:
        front = c.question.replace("\t", " ").replace("\n", "<br>")
        back = c.answer.replace("\t", " ").replace("\n", "<br>")
        tags = f"{c.course_id} {c.difficulty} page_{c.page}"
        lines.append(f"{front}\t{back}\t{tags}")
    return "\n".join(lines)
