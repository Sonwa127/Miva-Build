"""Dynamic quiz generation and scoring grounded in course materials."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .jsonparse import parse_json_list
from .llm import LLMError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quizzes (
    id             TEXT PRIMARY KEY,
    course_id      TEXT NOT NULL DEFAULT '',
    doc_id         TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL,
    question_count INTEGER NOT NULL DEFAULT 5,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id            TEXT PRIMARY KEY,
    quiz_id       TEXT NOT NULL,
    question      TEXT NOT NULL,
    choices       TEXT NOT NULL,  -- JSON list of strings
    correct_index INTEGER NOT NULL,
    explanation   TEXT NOT NULL DEFAULT '',
    source_page   INTEGER NOT NULL DEFAULT 1,
    source_text   TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id           TEXT PRIMARY KEY,
    quiz_id      TEXT NOT NULL,
    score        REAL NOT NULL,
    total        INTEGER NOT NULL,
    answers      TEXT NOT NULL,   -- JSON list of user selected indices
    completed_at TEXT NOT NULL,
    FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class QuizQuestion:
    id: str
    quiz_id: str
    question: str
    choices: list[str]
    correct_index: int
    explanation: str
    source_page: int
    source_text: str


@dataclass
class Quiz:
    id: str
    course_id: str
    doc_id: str
    title: str
    question_count: int
    created_at: str
    questions: list[QuizQuestion] = field(default_factory=list)


@dataclass
class QuizResult:
    attempt_id: str
    quiz_id: str
    score: float
    total: int
    percentage: float
    results: list[dict]
    completed_at: str


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


def generate_quiz(
    doc_id: str,
    store,
    llm,
    course_id: str = "",
    num_questions: int = 5,
    topic: str = "",
) -> Quiz:
    if topic:
        hits = store.search(topic, k=min(num_questions * 3, 20), doc_id=doc_id)
        chunks_info = [{"page": h.page, "text": h.text, "title": h.title} for h in hits]
    else:
        raw_chunks = store.list_chunks(doc_id)
        chunks_info = [{"page": r[0], "text": r[3], "title": doc_id} for r in raw_chunks[:25]]

    if not chunks_info:
        raise ValueError(f"No text chunks found for document '{doc_id}' to generate quiz.")

    context_str = "\n\n".join(
        f"[Page {c['page']}] {c['text'][:500]}" for c in chunks_info[:12]
    )

    system_prompt = (
        "You are an academic assessment designer. Create an adaptive multiple-choice practice quiz "
        "based strictly on the provided lecture excerpts.\n"
        f"Generate {num_questions} multiple choice questions.\n"
        "Each question must test conceptual understanding or algorithmic mechanics.\n"
        "Return ONLY a valid JSON array of objects with keys:\n"
        "- 'question': The question text\n"
        "- 'choices': Array of exactly 4 strings (options A, B, C, D)\n"
        "- 'correct_index': Integer 0-3 indicating the correct choice\n"
        "- 'explanation': Clear explanation grounded in the excerpt\n"
        "- 'page': Integer page number where this concept is defined\n"
        "Do not include markdown or backticks."
    )

    user_prompt = f"EXCERPTS:\n\n{context_str}\n\nTOPIC: {topic or 'Core Concepts'}"

    items = parse_json_list(llm.complete(system_prompt, user_prompt, temperature=0.2, max_tokens=3500))
    if not items:
        raise LLMError("The AI replied, but its quiz could not be read. Nothing was published. Please try again.")

    quiz_id = f"q_{uuid.uuid4().hex[:10]}"
    title = f"{topic or 'Practice Quiz'} ({chunks_info[0]['title'] if chunks_info else 'Lecture'})"
    now = now_iso()

    created_questions: list[QuizQuestion] = []
    with get_db() as c:
        c.execute(
            """INSERT INTO quizzes (id, course_id, doc_id, title, question_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (quiz_id, course_id, doc_id, title, len(items), now),
        )

        for item in items[:num_questions]:
            qid = f"qq_{uuid.uuid4().hex[:10]}"
            q_text = str(item.get("question", "")).strip()
            choices = item.get("choices", ["A", "B", "C", "D"])[:4]
            while len(choices) < 4:
                choices.append("N/A")
            c_idx = int(item.get("correct_index", 0)) % 4
            expl = str(item.get("explanation", "")).strip()
            page = int(item.get("page", chunks_info[0]["page"]))

            c.execute(
                """INSERT INTO quiz_questions (id, quiz_id, question, choices, correct_index, explanation, source_page, source_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (qid, quiz_id, q_text, json.dumps(choices), c_idx, expl, page, f"Page {page}"),
            )
            created_questions.append(QuizQuestion(
                id=qid,
                quiz_id=quiz_id,
                question=q_text,
                choices=choices,
                correct_index=c_idx,
                explanation=expl,
                source_page=page,
                source_text=f"Page {page}",
            ))

    return Quiz(
        id=quiz_id,
        course_id=course_id,
        doc_id=doc_id,
        title=title,
        question_count=len(created_questions),
        created_at=now,
        questions=created_questions,
    )


def get_quiz(quiz_id: str) -> Quiz | None:
    with get_db() as c:
        q_row = c.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        if not q_row:
            return None

        qq_rows = c.execute("SELECT * FROM quiz_questions WHERE quiz_id = ?", (quiz_id,)).fetchall()
        questions = []
        for r in qq_rows:
            questions.append(QuizQuestion(
                id=r["id"],
                quiz_id=r["quiz_id"],
                question=r["question"],
                choices=json.loads(r["choices"]),
                correct_index=r["correct_index"],
                explanation=r["explanation"],
                source_page=r["source_page"],
                source_text=r["source_text"],
            ))

    return Quiz(
        id=q_row["id"],
        course_id=q_row["course_id"],
        doc_id=q_row["doc_id"],
        title=q_row["title"],
        question_count=q_row["question_count"],
        created_at=q_row["created_at"],
        questions=questions,
    )


def list_quizzes(course_id: str | None = None) -> list[Quiz]:
    with get_db() as c:
        if course_id:
            rows = c.execute("SELECT * FROM quizzes WHERE course_id = ? ORDER BY created_at DESC", (course_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM quizzes ORDER BY created_at DESC").fetchall()

    return [Quiz(
        id=r["id"],
        course_id=r["course_id"],
        doc_id=r["doc_id"],
        title=r["title"],
        question_count=r["question_count"],
        created_at=r["created_at"],
    ) for r in rows]


def submit_quiz(quiz_id: str, answers: list[int]) -> QuizResult:
    quiz = get_quiz(quiz_id)
    if not quiz:
        raise ValueError(f"Quiz '{quiz_id}' not found.")

    total = len(quiz.questions)
    correct_count = 0
    results = []

    for i, q in enumerate(quiz.questions):
        user_choice = answers[i] if i < len(answers) else -1
        is_correct = (user_choice == q.correct_index)
        if is_correct:
            correct_count += 1
        results.append({
            "question_id": q.id,
            "question": q.question,
            "choices": q.choices,
            "user_choice": user_choice,
            "correct_index": q.correct_index,
            "is_correct": is_correct,
            "explanation": q.explanation,
            "source_page": q.source_page,
        })

    score = correct_count
    pct = round((correct_count / max(total, 1)) * 100, 1)
    attempt_id = f"att_{uuid.uuid4().hex[:10]}"
    now = now_iso()

    with get_db() as c:
        c.execute(
            """INSERT INTO quiz_attempts (id, quiz_id, score, total, answers, completed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (attempt_id, quiz_id, score, total, json.dumps(answers), now),
        )

    return QuizResult(
        attempt_id=attempt_id,
        quiz_id=quiz_id,
        score=score,
        total=total,
        percentage=pct,
        results=results,
        completed_at=now,
    )


def get_quiz_history(course_id: str | None = None) -> list[dict]:
    with get_db() as c:
        query = """
            SELECT a.*, q.title, q.course_id
            FROM quiz_attempts a
            JOIN quizzes q ON a.quiz_id = q.id
        """
        params = []
        if course_id:
            query += " WHERE q.course_id = ?"
            params.append(course_id)
        query += " ORDER BY a.completed_at DESC"
        rows = c.execute(query, params).fetchall()

    return [
        {
            "id": r["id"],
            "quiz_id": r["quiz_id"],
            "title": r["title"],
            "course_id": r["course_id"],
            "score": r["score"],
            "total": r["total"],
            "percentage": round((r["score"] / max(r["total"], 1)) * 100, 1),
            "completed_at": r["completed_at"],
        }
        for r in rows
    ]
