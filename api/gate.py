"""Require a student (or administrator) login for every page when ARCHIVE_REQUIRE_LOGIN=1."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from archive import accounts, config

from .auth import is_admin

# Pages a signed-out visitor may open. The admin area does its own login check.
_PUBLIC_EXACT = {"/login", "/signup", "/verify", "/forgot", "/logout", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/static/", "/admin/", "/api/admin/")


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT or path in {"/admin", "/api/admin"} or path.startswith(_PUBLIC_PREFIXES)


async def login_gate(request: Request, call_next):
    if not config.REQUIRE_LOGIN or is_public_path(request.url.path) or is_admin(request):
        return await call_next(request)
    account = await run_in_threadpool(accounts.account_from_cookie, request.cookies.get(accounts.COOKIE_NAME))
    if account:
        return await call_next(request)
    if request.method in {"GET", "HEAD"} and not request.url.path.startswith("/api/"):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
    return JSONResponse({"detail": "Please sign in."}, status_code=401)
