"""API users and tokens.

Each user has a name, a role and one secret token. The token is shown once, when it is
created. Only a SHA-256 hash of it is stored, so a copy of the database does not reveal
working tokens. (Tokens are long random strings, so a fast hash is safe here; slow hashes
like bcrypt are for human-chosen passwords.)

Roles, from least to most powerful:
    reader       search and ask
    contributor  reader + ingest documents
    admin        contributor + remove documents and manage users
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

ROLES = ("reader", "contributor", "admin")          # lowest to highest
TOKEN_PREFIX = "ca_"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name       TEXT PRIMARY KEY,
    role       TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""


@dataclass
class User:
    name: str
    role: str
    created_at: str = ""


@contextmanager
def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.USERS_DB)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _clean_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME.match(name):
        raise ValueError("Names must be 1-32 characters: letters, digits, '.', '_' or '-', "
                         "starting with a letter or digit.")
    return name


def add_user(name: str, role: str = "reader") -> str:
    """Create a user and return their token. This is the only time the token is visible."""
    name = _clean_name(name)
    if role not in ROLES:
        raise ValueError(f"Unknown role '{role}'. Choose one of: {', '.join(ROLES)}.")
    token = _new_token()
    try:
        with _conn() as c:
            c.execute("INSERT INTO users (name, role, token_hash, created_at) VALUES (?,?,?,?)",
                      (name, role, _hash(token), _now()))
    except sqlite3.IntegrityError:
        raise ValueError(f"A user named '{name}' already exists.") from None
    return token


def list_users() -> list[User]:
    with _conn() as c:
        rows = c.execute("SELECT name, role, created_at FROM users ORDER BY name").fetchall()
    return [User(r["name"], r["role"], r["created_at"]) for r in rows]


def remove_user(name: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM users WHERE name = ?", ((name or "").strip().lower(),))
        return cur.rowcount > 0


def reset_token(name: str) -> str | None:
    """Replace a user's token (for a lost or leaked one). Returns the new token, or None
    if there is no such user. The old token stops working immediately."""
    token = _new_token()
    with _conn() as c:
        cur = c.execute("UPDATE users SET token_hash = ? WHERE name = ?",
                        (_hash(token), (name or "").strip().lower()))
        return token if cur.rowcount > 0 else None


def authenticate(token: str | None) -> User | None:
    """Return the user who owns this token, or None. An API layer calls this on every request."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    with _conn() as c:
        row = c.execute("SELECT name, role, created_at FROM users WHERE token_hash = ?",
                        (_hash(token.strip()),)).fetchone()
    return User(row["name"], row["role"], row["created_at"]) if row else None


def has_role(user: User | None, minimum: str) -> bool:
    """True if the user's role is at least `minimum` (admin passes every check)."""
    if user is None or user.role not in ROLES or minimum not in ROLES:
        return False
    return ROLES.index(user.role) >= ROLES.index(minimum)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
