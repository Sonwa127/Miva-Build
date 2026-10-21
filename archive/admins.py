"""Collaborator admins and the activity log.

A collaborator is an ordinary student account that the owner has made an admin. They sign in
to /admin/login with the same email and password they use as a student, so there is nothing
extra to remember and nothing to hand over. One of them is marked as an owner, and owners are
the only admins who can add or remove admins. The main admin password still works as a
recovery login and counts as an owner.

Because the login is the student account, disabling that account, deleting it, or resetting its
password also ends its admin sessions at once.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import accounts
from .accounts import _db, _now_iso

MAX_ACTIVITY_ROWS = 20000

_SELECT = ("SELECT a.id, a.email, a.disabled, a.session_version, a.last_login_at, g.name, g.granted_at, g.is_owner "
           "FROM admins g JOIN accounts a ON a.id = g.account_id")


@dataclass(frozen=True)
class Admin:
    id: int                  # the student account's id
    email: str
    name: str                # shown in the activity log
    disabled: bool
    session_version: int
    created_at: str          # when admin rights were granted
    last_login_at: str | None
    is_owner: bool = False   # owners can add and remove admins


def _admin(row) -> Admin | None:
    if row is None:
        return None
    return Admin(row["id"], row["email"], row["name"], bool(row["disabled"]), row["session_version"],
                 row["granted_at"], row["last_login_at"], bool(row["is_owner"]))


def clean_name(raw: str | None) -> str | None:
    name = " ".join((raw or "").split())
    if not name or len(name) > 60 or any(ord(ch) < 32 for ch in name):
        return None
    return name


# --------------------------------------------------------------------- collaborators
def get_admin(account_id: int) -> Admin | None:
    with _db() as c:
        return _admin(c.execute(_SELECT + " WHERE g.account_id=?", (account_id,)).fetchone())


def list_admins() -> list[Admin]:
    with _db() as c:
        return [_admin(r) for r in c.execute(_SELECT + " ORDER BY g.name COLLATE NOCASE").fetchall()]


def make_admin(account_id: int, name: str | None = None) -> Admin:
    """Give a student account admin rights. The name appears in the activity log."""
    account = accounts.get_account(account_id)
    if not account:
        raise ValueError("No student account with that email. They need to sign up first with the cohort code.")
    if account.disabled:
        raise ValueError("That account is disabled. Enable it first.")
    if get_admin(account_id):
        raise ValueError("That person is already an admin.")
    shown = clean_name(name) if name else clean_name(account.email.split("@")[0])
    if not shown:
        raise ValueError("Enter a name up to 60 characters.")
    with _db() as c:
        c.execute("INSERT INTO admins(account_id, name, granted_at) VALUES(?,?,?)", (account_id, shown, _now_iso()))
    return get_admin(account_id)


def set_owner(account_id: int, owner: bool = True) -> Admin:
    """Make an existing admin an owner (or not). Owners add and remove admins."""
    if not get_admin(account_id):
        raise ValueError("That person is not an admin yet.")
    with _db() as c:
        c.execute("UPDATE admins SET is_owner=? WHERE account_id=?", (1 if owner else 0, account_id))
    return get_admin(account_id)


def remove_admin(account_id: int) -> bool:
    """Take admin rights away. The student account stays. Their admin sessions end at once."""
    with _db() as c:
        return c.execute("DELETE FROM admins WHERE account_id=?", (account_id,)).rowcount == 1


def authenticate_admin(email: str | None, password: str) -> Admin | None:
    """Student email and password, and the account must hold admin rights.

    Wrong password, unknown email, disabled account and 'not an admin' all fail the same way.
    """
    account = accounts.authenticate(email, password)
    return get_admin(account.id) if account else None


def is_admin_account(account_id: int) -> bool:
    return get_admin(account_id) is not None


# ------------------------------------------------------------------------- activity
def log_activity(actor_kind: str, actor_id: int | None, actor_name: str, action: str, detail: str = "") -> None:
    """Record who did what. Never raises: a logging problem must not break the admin's action."""
    try:
        with _db() as c:
            c.execute("INSERT INTO activity(at, actor_kind, actor_id, actor_name, action, detail) VALUES(?,?,?,?,?,?)",
                      (_now_iso(), actor_kind, actor_id, actor_name[:80], action[:120], detail[:300]))
            if c.execute("SELECT COUNT(*) FROM activity").fetchone()[0] > MAX_ACTIVITY_ROWS:
                c.execute("DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - ?", (MAX_ACTIVITY_ROWS,))
    except Exception:
        pass


def list_activity(limit: int = 200, actor: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 1000))
    with _db() as c:
        if actor:
            rows = c.execute("SELECT * FROM activity WHERE actor_name=? ORDER BY id DESC LIMIT ?", (actor, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def activity_actors() -> list[str]:
    with _db() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT actor_name FROM activity ORDER BY actor_name COLLATE NOCASE")]
