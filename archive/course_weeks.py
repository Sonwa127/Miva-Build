"""Weekly course outlines. Week zero is reserved for general course materials."""
import sqlite3
from contextlib import contextmanager

from . import config


@contextmanager
def connection():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.APP_DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS course_weeks (
        course TEXT NOT NULL, number INTEGER NOT NULL CHECK(number BETWEEN 1 AND 52),
        title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (course, number)
    )""")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def list_weeks(course: str | None = None) -> list[dict]:
    with connection() as con:
        if course is None:
            rows = con.execute("SELECT * FROM course_weeks ORDER BY course, number").fetchall()
        else:
            rows = con.execute("SELECT * FROM course_weeks WHERE course = ? ORDER BY number", (course,)).fetchall()
    return [dict(row) for row in rows]


def save_week(course: str, number: int, title: str = "", description: str = "") -> dict:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 52:
        raise ValueError("Week number must be between 1 and 52.")
    with connection() as con:
        con.execute("""INSERT INTO course_weeks (course, number, title, description) VALUES (?, ?, ?, ?)
            ON CONFLICT(course, number) DO UPDATE SET title=excluded.title, description=excluded.description""",
            (course, number, title.strip(), description.strip()))
    return {"course": course, "number": number, "title": title.strip(), "description": description.strip()}


def validate_placement(course: str, week: int) -> None:
    if isinstance(week, bool) or not isinstance(week, int) or not 0 <= week <= 52:
        raise ValueError("Choose General course materials or a week between 1 and 52.")
    if week and (not course or not any(item["number"] == week for item in list_weeks(course))):
        raise ValueError("Create this week for the selected course before assigning materials to it.")


def delete_week(course: str, number: int) -> bool:
    with connection() as con:
        return con.execute("DELETE FROM course_weeks WHERE course = ? AND number = ?", (course, number)).rowcount > 0
