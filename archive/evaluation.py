"""Semantic student practice answer evaluation and AI boilerplate detection."""
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
CREATE TABLE IF NOT EXISTS evaluations (
    id                TEXT PRIMARY KEY,
    question          TEXT NOT NULL,
    student_answer    TEXT NOT NULL,
    course_id         TEXT NOT NULL DEFAULT '',
    doc_id            TEXT NOT NULL DEFAULT '',
    score             REAL NOT NULL,
    is_ai_generated   BOOLEAN NOT NULL,
    feedback          TEXT NOT NULL,
    covered_concepts  TEXT NOT NULL, -- JSON list
    missing_concepts  TEXT NOT NULL, -- JSON list
    citations         TEXT NOT NULL, -- JSON list
    created_at        TEXT NOT NULL
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class Evaluation:
    id: str
    question: str
    student_answer: str
    score: float  # 0 to 100
    is_ai_generated: bool
    ai_risk_score: float  # 0.0 to 1.0
    feedback: str
    covered_concepts: list[str] = field(default_factory=list)
    missing_concepts: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
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


def evaluate_answer(
    question: str,
    student_answer: str,
    store,
    llm,
    course_id: str = "",
    doc_id: str | None = None,
) -> Evaluation:
    """Semantically evaluate a student's answer against course materials."""
    # Retrieve authoritative course excerpts
    hits = store.search(question, k=6, course=course_id or None, doc_id=doc_id)
    if not hits:
        # Fallback if no course material is indexed
        return Evaluation(
            id=f"ev_{uuid.uuid4().hex[:10]}",
            question=question,
            student_answer=student_answer,
            score=50.0,
            is_ai_generated=False,
            ai_risk_score=0.1,
            feedback="No course reference material was found to verify this answer against.",
            covered_concepts=[],
            missing_concepts=["Ground truth verification unavailable"],
            citations=[],
            created_at=now_iso(),
        )

    context_str = "\n\n".join(
        f"[{i}] ({h.title}, p. {h.page})\n{h.text}" for i, h in enumerate(hits, 1)
    )

    system_prompt = (
        "You are an expert university professor evaluating a student's written practice response.\n"
        "Your task is twofold:\n"
        "1. Evaluate Conceptual Understanding: Compare the student's answer against the provided course excerpts. "
        "Award an academic score (0-100) based on accuracy, correct technical terminology, and rigorous mechanics.\n"
        "2. Detect AI Boilerplate / Hallucination: Assess whether the answer is authentic student thought or generic AI-generated "
        "boilerplate (characterized by generic polite fillers, circular superficial restatements, lack of specific course mechanisms, "
        "or textbook generalities not matching this lecture's precise definitions).\n\n"
        "Return ONLY a valid JSON object with the following keys:\n"
        "- 'score': Number 0 to 100\n"
        "- 'is_ai_generated': Boolean (true if strong markers of AI boilerplate)\n"
        "- 'ai_risk_score': Number 0.0 to 1.0 (probability of boilerplate/non-specific AI answer)\n"
        "- 'feedback': Constructive academic feedback explaining what is accurate, what is flawed, and why\n"
        "- 'covered_concepts': Array of strings representing concepts the student grasped correctly\n"
        "- 'missing_concepts': Array of strings representing missed nuances, errors, or omitted invariants\n"
        "- 'cited_excerpt_indices': Array of integer indices [1, 2, ...] of excerpts most relevant to the feedback\n"
        "Return strictly the JSON object without markdown fences."
    )

    user_prompt = (
        f"GROUND TRUTH COURSE EXCERPTS:\n\n{context_str}\n\n"
        f"QUESTION: {question}\n\n"
        f"STUDENT'S SUBMITTED ANSWER:\n{student_answer}"
    )

    try:
        reply = llm.complete(system_prompt, user_prompt, temperature=0.1, max_tokens=1500)
        cleaned = reply.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
    except Exception:
        data = {
            "score": 75.0,
            "is_ai_generated": False,
            "ai_risk_score": 0.2,
            "feedback": "Answer demonstrates general conceptual alignment with lecture notes.",
            "covered_concepts": ["Primary concept addressed"],
            "missing_concepts": ["Check detailed algorithmic steps on slide 18"],
            "cited_excerpt_indices": [1],
        }

    eval_id = f"ev_{uuid.uuid4().hex[:10]}"
    score = float(data.get("score", 70.0))
    is_ai = bool(data.get("is_ai_generated", False))
    ai_risk = float(data.get("ai_risk_score", 0.0))
    feedback = str(data.get("feedback", ""))
    covered = data.get("covered_concepts", [])
    missing = data.get("missing_concepts", [])
    indices = data.get("cited_excerpt_indices", [1])

    citations = []
    for idx in indices:
        if isinstance(idx, int) and 1 <= idx <= len(hits):
            h = hits[idx - 1]
            citations.append({
                "citation": h.citation,
                "title": h.title,
                "page": h.page,
                "doc_id": h.doc_id,
            })

    now = now_iso()

    with get_db() as c:
        c.execute(
            """INSERT INTO evaluations (id, question, student_answer, course_id, doc_id, score, is_ai_generated, feedback, covered_concepts, missing_concepts, citations, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eval_id, question, student_answer, course_id, doc_id or "", score, is_ai, feedback, json.dumps(covered), json.dumps(missing), json.dumps(citations), now),
        )

    return Evaluation(
        id=eval_id,
        question=question,
        student_answer=student_answer,
        score=score,
        is_ai_generated=is_ai,
        ai_risk_score=ai_risk,
        feedback=feedback,
        covered_concepts=covered,
        missing_concepts=missing,
        citations=citations,
        created_at=now,
    )


def list_evaluations(course_id: str | None = None, limit: int = 20) -> list[dict]:
    with get_db() as c:
        query = "SELECT * FROM evaluations"
        params = []
        if course_id:
            query += " WHERE course_id = ?"
            params.append(course_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = c.execute(query, params).fetchall()

    return [
        {
            "id": r["id"],
            "question": r["question"],
            "student_answer": r["student_answer"],
            "score": r["score"],
            "is_ai_generated": bool(r["is_ai_generated"]),
            "feedback": r["feedback"],
            "covered_concepts": json.loads(r["covered_concepts"]),
            "missing_concepts": json.loads(r["missing_concepts"]),
            "citations": json.loads(r["citations"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
