"""Executive chapter and document summaries grounded in course materials."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .llm import LLMError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    id           TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    course_id    TEXT NOT NULL DEFAULT '',
    chapter      TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    key_concepts TEXT NOT NULL,  -- JSON list of strings
    source_pages TEXT NOT NULL,  -- JSON list of ints
    created_at   TEXT NOT NULL
);
"""

DB_PATH = config.DATA_DIR / "app.sqlite"


@dataclass
class Summary:
    id: str
    doc_id: str
    course_id: str
    chapter: str
    title: str
    summary_text: str
    key_concepts: list[str] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)
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


def generate_summary(
    doc_id: str,
    store,
    llm,
    course_id: str = "",
    chapter: str = "",
    max_pages: int = 15,
) -> Summary:
    raw_chunks = store.list_chunks(doc_id)
    if chapter:
        filtered = [r for r in raw_chunks if chapter.lower() in (r[2] or "").lower()]
        chunks_to_use = filtered if filtered else raw_chunks
    else:
        chunks_to_use = raw_chunks

    if not chunks_to_use:
        raise ValueError(f"No chunks found for document '{doc_id}'.")

    # Group text by page
    page_texts: dict[int, list[str]] = {}
    for page, _, _, text in chunks_to_use:
        page_texts.setdefault(page, []).append(text)

    sorted_pages = sorted(page_texts.keys())[:max_pages]
    excerpt_blocks = []
    for p in sorted_pages:
        excerpt_blocks.append(f"[Page {p}]\n" + "\n".join(page_texts[p])[:800])

    context_str = "\n\n".join(excerpt_blocks)

    system_prompt = (
        "You are an academic researcher. Synthesize an executive study summary from the provided course notes.\n"
        "Return a strictly valid JSON object with the following keys:\n"
        "- 'title': High-level title for this chapter/document summary\n"
        "- 'summary_text': Markdown-formatted structured executive summary (overview, key mechanisms, exam takeaways)\n"
        "- 'key_concepts': Array of 4-8 core conceptual terms or theorems defined in the text\n"
        "- 'source_pages': Array of page numbers cited in this summary\n"
        "Return ONLY the JSON object without markdown or code fences."
    )

    user_prompt = f"EXCERPTS:\n\n{context_str}\n\nFOCUS: {chapter or 'Full Lecture'}"

    reply = llm.complete(system_prompt, user_prompt, temperature=0.2, max_tokens=3000)   # AI errors reach the admin
    try:
        body = re.sub(r"```(?:json)?", "", reply).strip()
        data = json.loads(body[body.index("{"):body.rindex("}") + 1], strict=False)   # strict=False: real line breaks inside strings
        if not isinstance(data, dict) or not str(data.get("summary_text", "")).strip():
            raise ValueError("empty summary")
    except ValueError:
        raise LLMError("The AI replied, but its summary could not be read. Nothing was published. Please try again.") from None

    sum_id = f"sm_{uuid.uuid4().hex[:10]}"
    title = data.get("title", f"Summary of {doc_id}")
    summary_text = data.get("summary_text", "")
    key_concepts = data.get("key_concepts", [])
    source_pages = data.get("source_pages", sorted_pages)
    now = now_iso()

    with get_db() as c:
        c.execute(
            """INSERT INTO summaries (id, doc_id, course_id, chapter, title, summary_text, key_concepts, source_pages, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sum_id, doc_id, course_id, chapter, title, summary_text, json.dumps(key_concepts), json.dumps(source_pages), now),
        )

    return Summary(
        id=sum_id,
        doc_id=doc_id,
        course_id=course_id,
        chapter=chapter,
        title=title,
        summary_text=summary_text,
        key_concepts=key_concepts,
        source_pages=source_pages,
        created_at=now,
    )


def get_summaries(doc_id: str | None = None, course_id: str | None = None) -> list[Summary]:
    query = "SELECT * FROM summaries"
    filters = []
    params = []
    if doc_id:
        filters.append("doc_id = ?")
        params.append(doc_id)
    if course_id:
        filters.append("course_id = ?")
        params.append(course_id)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY created_at DESC"

    with get_db() as c:
        rows = c.execute(query, params).fetchall()

    return [
        Summary(
            id=r["id"],
            doc_id=r["doc_id"],
            course_id=r["course_id"],
            chapter=r["chapter"],
            title=r["title"],
            summary_text=r["summary_text"],
            key_concepts=json.loads(r["key_concepts"]),
            source_pages=json.loads(r["source_pages"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
