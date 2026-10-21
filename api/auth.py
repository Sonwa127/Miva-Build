"""Password-protected administration with revocable signed sessions."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from archive import admins, config

COOKIE_NAME = "studyarchive_admin"
SESSION_SECONDS = 8 * 60 * 60


def credential_path() -> Path:
    return config.DATA_DIR / "admin_credentials.json"


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


def load_credentials() -> dict | None:
    path = credential_path()
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def configure_admin(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Use a password of at least 12 characters.")
    salt = secrets.token_hex(16)
    credentials = {"salt": salt, "hash": password_hash(password, salt), "secret": secrets.token_hex(32)}
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(credentials), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


def check_password(password: str) -> bool:
    credentials = load_credentials()
    return bool(credentials and hmac.compare_digest(password_hash(password, credentials["salt"]), credentials["hash"]))


def can_setup_locally(request: Request) -> bool:
    """First-run setup is available only from a browser on the server itself."""
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1"} or not request.client:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


OWNER_NAME = "Owner"


@dataclass(frozen=True)
class Identity:
    """Who is signed in to the admin area: the owner (main password) or a collaborator."""
    kind: str                       # "owner" or "admin"
    id: int | None
    name: str
    email: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.kind == "owner"


def issue_session(admin: admins.Admin | None = None) -> str:
    """Sign a session cookie. Without an admin it is the owner's session (the main password)."""
    credentials = load_credentials()
    if not credentials:
        raise HTTPException(503, "The administrator account has not been configured.")
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    if admin:
        payload += f".{admin.id}.{admin.session_version}"
    signature = hmac.new(bytes.fromhex(credentials["secret"]), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def identity(request: Request) -> Identity | None:
    token = request.cookies.get(COOKIE_NAME, "")
    if len(token) > 300:
        return None
    parts = token.split(".")
    if len(parts) not in (3, 5):
        return None
    try:
        credentials = load_credentials()
        if not credentials or int(parts[0]) <= time.time():
            return None
        expected = hmac.new(bytes.fromhex(credentials["secret"]), ".".join(parts[:-1]).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, parts[-1]):
            return None
        if len(parts) == 3:
            return Identity("owner", None, OWNER_NAME)
        admin = admins.get_admin(int(parts[2]))
        if not admin or admin.disabled or admin.session_version != int(parts[3]):
            return None
        return Identity("admin", admin.id, admin.name, admin.email)
    except (ValueError, KeyError):
        return None


def is_admin(request: Request) -> bool:
    return identity(request) is not None


def audit(request: Request, action: str, detail: str = "") -> None:
    """Write one line to the activity log in the name of whoever made this request."""
    who = identity(request)
    if who:
        admins.log_activity(who.kind, who.id, who.name, action, detail)


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site administration requests are not allowed.")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise HTTPException(403, "Cross-site administration requests are not allowed.")


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "Administrator login required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)


def require_owner(request: Request) -> None:
    who = identity(request)
    if not who:
        raise HTTPException(401, "Administrator login required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
    if not who.is_owner:
        raise HTTPException(403, "Only the owner can do this.")
