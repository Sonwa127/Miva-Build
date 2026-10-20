"""Password-protected administration with revocable signed sessions."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from archive import config

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


def issue_session() -> str:
    credentials = load_credentials()
    if not credentials:
        raise HTTPException(503, "The administrator account has not been configured.")
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    signature = hmac.new(bytes.fromhex(credentials["secret"]), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def is_admin(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME, "")
    if len(token) > 200:
        return False
    try:
        expiry, nonce, signature = token.split(".")
        credentials = load_credentials()
        if not credentials or int(expiry) <= time.time():
            return False
        expected = hmac.new(bytes.fromhex(credentials["secret"]), f"{expiry}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except (ValueError, KeyError):
        return False


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
