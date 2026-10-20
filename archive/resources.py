"""Curated video and web resources, shared with the whole class."""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config
from .media import resolve_media


@contextmanager
def connection():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.APP_DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS resources (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        course TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, url TEXT NOT NULL,
        video_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    )""")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def normalize_url(url: str, kind: str) -> tuple[str, str]:
    media = resolve_media(url, kind)
    return media.url, media.video_id


def _present(row) -> dict:
    result = dict(row)
    try:
        media = resolve_media(result["url"], result["kind"])
        result.update(kind=media.kind, provider=media.provider, embed_url=media.embed_url,
                      is_playlist=media.is_playlist, is_video=bool(media.embed_url), player_type=media.player_type)
    except ValueError:
        # An obsolete or corrupted stored link must never become arbitrary iframe HTML.
        result.update(provider="Website", embed_url="", is_playlist=False, is_video=False, player_type="")
    return result


def list_resources(course: str | None = None) -> list[dict]:
    with connection() as con:
        if course:
            rows = con.execute("SELECT * FROM resources WHERE course = ? ORDER BY created_at DESC, id", (course,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM resources ORDER BY created_at DESC, id").fetchall()
    return [_present(row) for row in rows]


def get_resource(resource_id: str) -> dict | None:
    with connection() as con:
        row = con.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    return _present(row) if row else None


def save_resource(title: str, description: str, course: str, kind: str, url: str, resource_id: str | None = None) -> dict:
    media = resolve_media(url, kind)
    url, video_id, kind = media.url, media.video_id, media.kind
    resource_id = resource_id or f"r_{uuid.uuid4().hex[:16]}"
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as con:
        con.execute("""INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title, description=excluded.description,
            course=excluded.course, kind=excluded.kind, url=excluded.url, video_id=excluded.video_id""",
            (resource_id, title.strip(), description.strip(), course, kind, url, video_id, created_at))
    return get_resource(resource_id)


def delete_resource(resource_id: str) -> bool:
    with connection() as con:
        return con.execute("DELETE FROM resources WHERE id = ?", (resource_id,)).rowcount > 0
