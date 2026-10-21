"""Student accounts: school-email signup, one-time links, passwords and signed sessions.

Flow
  1. The administrator generates a cohort code and shares it in the class group.
  2. A student signs up with a school email, the cohort code and a password they choose.
  3. They sign in with email and password. A signed cookie keeps them signed in.
  4. A forgotten password is fixed by the administrator, who creates a one-time reset
     link and sends it to the student (there is no email sending at all).

The administrator can also create a one-time sign-up link for any email address, for
example a classmate whose school email is not working. Only a hash of each link token
is stored, so a copy of the database cannot be used to take over an account.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock

from . import config

LINK_TTL_SECONDS = 24 * 60 * 60
SESSION_SECONDS = 14 * 24 * 60 * 60
COOKIE_NAME = "studyarchive_user"
MIN_PASSWORD = 10
MAX_PASSWORD = 256
PBKDF2_ROUNDS = 600_000
PURPOSES = {"signup", "reset"}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I, easy to read out loud
CODE_LENGTH = 12

_EMAIL_RE = re.compile(r"^[a-z0-9._%+'\-]{1,64}@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,100}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    session_version INTEGER NOT NULL DEFAULT 1,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS login_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE TABLE IF NOT EXISTS admins (
    account_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    is_owner INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id INTEGER,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    disabled: bool
    session_version: int
    created_at: str
    last_login_at: str | None


# ---------------------------------------------------------------- database helpers
@contextmanager
def _db():
    path = config.ACCOUNTS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        if "is_owner" not in {r[1] for r in conn.execute("PRAGMA table_info(admins)")}:
            conn.execute("ALTER TABLE admins ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")   # databases made before owners were accounts
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _account(row) -> Account | None:
    if row is None:
        return None
    return Account(row["id"], row["email"], bool(row["disabled"]), row["session_version"],
                   row["created_at"], row["last_login_at"])


_secret_cache: dict[str, bytes] = {}


def _secret() -> bytes:
    """Signing key for session cookies, created once and stored next to the accounts."""
    key = str(config.ACCOUNTS_DB)
    if key not in _secret_cache:
        with _db() as c:
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('session_secret', ?)",
                      (secrets.token_hex(32),))
            row = c.execute("SELECT value FROM meta WHERE key='session_secret'").fetchone()
        _secret_cache[key] = bytes.fromhex(row["value"])
    return _secret_cache[key]


# ------------------------------------------------------------------- email rules
def normalize_email(raw: str | None) -> str | None:
    """Lower-case a plausible email address, or return None if it does not look like one."""
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def domain_allowed(email: str) -> bool:
    """True if the address belongs to an allowed school domain (or one of its subdomains).

    With no domains configured, any address is accepted (the cohort code is the gate).
    """
    if not config.ALLOWED_EMAIL_DOMAINS:
        return True
    domain = email.rsplit("@", 1)[-1]
    return any(domain == d or domain.endswith("." + d) for d in config.ALLOWED_EMAIL_DOMAINS)


# ----------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def password_problem(password: str, email: str = "") -> str | None:
    """A human-readable reason the password is not acceptable, or None if it is fine."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return "That password is too long."
    local = email.split("@", 1)[0]
    if password.lower() in {email, local}:
        return "Choose a password that is not your email address."
    return None


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    return _DUMMY_HASH


# --------------------------------------------------------------------- accounts
def get_account_by_email(email: str) -> Account | None:
    with _db() as c:
        return _account(c.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone())


def get_account(account_id: int) -> Account | None:
    with _db() as c:
        return _account(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


def list_accounts() -> list[Account]:
    with _db() as c:
        return [_account(r) for r in c.execute("SELECT * FROM accounts ORDER BY email").fetchall()]


def authenticate(email: str | None, password: str) -> Account | None:
    """Check an email and password. Unknown and disabled accounts take as long as a real check."""
    email = normalize_email(email)
    with _db() as c:
        row = c.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone() if email else None
        stored = row["password_hash"] if row else _dummy_hash()
        ok = verify_password(password or "", stored)
        if not (row and ok) or row["disabled"]:
            return None
        c.execute("UPDATE accounts SET last_login_at=? WHERE id=?", (_now_iso(), row["id"]))
        return _account(c.execute("SELECT * FROM accounts WHERE id=?", (row["id"],)).fetchone())


def set_disabled(account_id: int, disabled: bool) -> bool:
    """Disable or re-enable an account. Disabling signs the person out everywhere."""
    with _db() as c:
        cur = c.execute("UPDATE accounts SET disabled=?, session_version=session_version+1 WHERE id=?",
                        (1 if disabled else 0, account_id))
        return cur.rowcount == 1


def delete_account(account_id: int) -> bool:
    with _db() as c:
        c.execute("DELETE FROM admins WHERE account_id=?", (account_id,))     # no orphaned admin rights
        return c.execute("DELETE FROM accounts WHERE id=?", (account_id,)).rowcount == 1


def create_account(email: str, password: str) -> Account:
    """Create an account directly (used after the cohort code has been checked)."""
    problem = password_problem(password, email)
    if problem:
        raise ValueError(problem)
    hashed = hash_password(password)
    try:
        with _db() as c:
            c.execute("INSERT INTO accounts(email, password_hash, created_at) VALUES(?,?,?)",
                      (email, hashed, _now_iso()))
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email already exists. Sign in, or ask your class admin for a reset link.") from None
    return get_account_by_email(email)


# --------------------------------------------------------------------- cohort code
def _norm_code(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def get_signup_code() -> str | None:
    """The current cohort code, formatted for sharing, or None if signups are closed."""
    with _db() as c:
        row = c.execute("SELECT value FROM meta WHERE key='signup_code'").fetchone()
    return format_code(row["value"]) if row else None


def new_signup_code() -> str:
    """Create (or replace) the cohort code. The old code stops working immediately."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    with _db() as c:
        c.execute("INSERT INTO meta(key, value) VALUES('signup_code', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (code,))
    return format_code(code)


def clear_signup_code() -> None:
    """Close signups. Existing accounts keep working."""
    with _db() as c:
        c.execute("DELETE FROM meta WHERE key='signup_code'")


def signup_code_matches(submitted: str | None) -> bool:
    with _db() as c:
        row = c.execute("SELECT value FROM meta WHERE key='signup_code'").fetchone()
    if not row:
        return False
    return hmac.compare_digest(_norm_code(submitted), row["value"])


# ------------------------------------------------------------------ one-time links
def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(email: str, purpose: str, ttl: int | None = None) -> str:
    """Create a one-time link token. Only one live link per email and purpose exists at a time."""
    if purpose not in PURPOSES:
        raise ValueError("Unknown token purpose.")
    raw = secrets.token_urlsafe(32)
    now = int(time.time())
    with _db() as c:
        c.execute("DELETE FROM login_tokens WHERE email=? AND purpose=?", (email, purpose))
        c.execute("DELETE FROM login_tokens WHERE expires_at < ?", (now - 86400,))
        c.execute("INSERT INTO login_tokens(token_hash, email, purpose, created_at, expires_at) VALUES(?,?,?,?,?)",
                  (_token_hash(raw), email, purpose, now, now + (ttl or LINK_TTL_SECONDS)))
    return raw


def peek_token(raw: str | None) -> dict | None:
    """Return the email and purpose of a link that is still usable, without using it up."""
    if not raw or not _TOKEN_RE.match(raw):
        return None
    with _db() as c:
        row = c.execute("SELECT email, purpose FROM login_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                        (_token_hash(raw), int(time.time()))).fetchone()
    return {"email": row["email"], "purpose": row["purpose"]} if row else None


def _consume_token(raw: str) -> dict | None:
    now = int(time.time())
    with _db() as c:
        cur = c.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                        (now, _token_hash(raw), now))
        if cur.rowcount != 1:
            return None
        row = c.execute("SELECT email, purpose FROM login_tokens WHERE token_hash=?", (_token_hash(raw),)).fetchone()
    return {"email": row["email"], "purpose": row["purpose"]}


def finish_with_password(raw: str, password: str) -> Account | None:
    """Use a one-time link to set a password: a sign-up link creates the account, a reset link changes it.

    Returns None if the link is invalid, expired or already used. Raises ValueError with a
    readable message if the password is not acceptable (the link is kept, so they can retry).
    """
    info = peek_token(raw)
    if not info:
        return None
    problem = password_problem(password, info["email"])
    if problem:
        raise ValueError(problem)
    used = _consume_token(raw)
    if not used:
        return None
    email = used["email"]
    hashed = hash_password(password)
    with _db() as c:
        row = c.execute("SELECT id FROM accounts WHERE email=?", (email,)).fetchone()
        if used["purpose"] == "reset":
            if not row:
                return None          # the account was deleted after the link was made
            # the old sessions stop working
            c.execute("UPDATE accounts SET password_hash=?, session_version=session_version+1 WHERE id=?",
                      (hashed, row["id"]))
        else:
            if row:
                return None          # a sign-up link never changes an existing account's password
            c.execute("INSERT INTO accounts(email, password_hash, created_at) VALUES(?,?,?)",
                      (email, hashed, _now_iso()))
    return get_account_by_email(email)


# ------------------------------------------------------------------------ sessions
def issue_session(account: Account) -> str:
    payload = f"{account.id}.{int(time.time()) + SESSION_SECONDS}.{account.session_version}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def account_from_cookie(value: str | None) -> Account | None:
    if not value or len(value) > 200:
        return None
    try:
        account_id, expiry, version, signature = value.split(".")
        expected = hmac.new(_secret(), f"{account_id}.{expiry}.{version}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature) or int(expiry) <= time.time():
            return None
        account = get_account(int(account_id))
    except ValueError:
        return None
    if not account or account.disabled or account.session_version != int(version):
        return None
    return account


# ----------------------------------------------------------------- abuse protection
class RateLimiter:
    """Allow `limit` attempts per key in `window` seconds. In memory, which suits one server process."""

    def __init__(self, limit: int, window: int, max_keys: int = 10000):
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= self.max_keys:
                for k in [k for k, q in self._hits.items() if not q or q[-1] < now - self.window]:
                    del self._hits[k]
                if key not in self._hits and len(self._hits) >= self.max_keys:
                    return False
            q = self._hits[key]
            while q and q[0] < now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def allowed(self, key: str) -> bool:
        """True if this key is still under its limit. Does not record an attempt."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return True
            return sum(1 for t in q if t >= now - self.window) < self.limit

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


wrong_code_by_ip = RateLimiter(10, 3600)    # counts only wrong codes, so classmates on a shared network are not blocked
login_by_ip = RateLimiter(20, 900)
login_by_email = RateLimiter(8, 900)


def reset_rate_limits() -> None:
    for limiter in (wrong_code_by_ip, login_by_ip, login_by_email):
        limiter.reset()


# ------------------------------------------------------------------------ helpers
def safe_next(value: str | None) -> str:
    """Only allow redirecting back to a page on this site."""
    value = value or "/"
    if (len(value) > 500 or not value.startswith("/") or value.startswith("//")
            or "\\" in value or any(ord(ch) < 32 for ch in value)):
        return "/"
    return value
