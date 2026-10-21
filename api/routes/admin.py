"""Administrator login endpoints. Students never need an account."""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from archive import accounts, admins

from ..auth import OWNER_NAME, audit, COOKIE_NAME, SESSION_SECONDS, can_setup_locally, check_origin, check_password, configure_admin, is_admin, issue_session, load_credentials, require_admin

router = APIRouter(prefix="/api/admin", tags=["Administration"])
_attempts: dict[str, deque] = defaultdict(deque)
_lock = Lock()
_setup_lock = Lock()


class LoginInput(BaseModel):
    password: str = Field(..., min_length=1, max_length=1024)
    email: str | None = Field(None, max_length=254)     # collaborators sign in with their student email; the owner leaves it empty


class SetupInput(BaseModel):
    password: str = Field(..., min_length=12, max_length=1024)
    confirmation: str = Field(..., min_length=12, max_length=1024)


@router.post("/setup", status_code=201)
def setup_admin(payload: SetupInput, request: Request, response: Response):
    check_origin(request)
    if not can_setup_locally(request):
        raise HTTPException(403, "For first-time setup, open http://localhost:8000/admin on the computer running the server.")
    if payload.password != payload.confirmation:
        raise HTTPException(422, "The passwords do not match. Please enter them again.")
    with _setup_lock:
        if load_credentials():
            raise HTTPException(409, "An administrator password is already set. Sign in with your existing password.")
        configure_admin(payload.password)
    response.set_cookie(COOKIE_NAME, issue_session(), max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response):
    check_origin(request)
    if not load_credentials():
        raise HTTPException(503, "Run python manage_admin.py on the server to set your administrator password.")
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        # Bound memory even if a public deployment receives many login attempts.
        for key in list(_attempts):
            if not _attempts[key] or _attempts[key][-1] < now - 600:
                del _attempts[key]
        if host not in _attempts and len(_attempts) >= 10000:
            raise HTTPException(429, "Too many login attempts. Try again later.")
        attempts = _attempts[host]
        while attempts and attempts[0] < now - 600:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, "Too many login attempts. Try again in ten minutes.")
        attempts.append(now)
    member = None
    if (payload.email or "").strip():
        email = accounts.normalize_email(payload.email) or payload.email.strip().lower()[:100]
        if not accounts.login_by_email.hit("admin:" + email):
            raise HTTPException(429, "Too many attempts for this email. Try again in 15 minutes.")
        member = admins.authenticate_admin(email, payload.password)
        if not member:
            raise HTTPException(401, "Incorrect email or password.")
        accounts.login_by_email.reset("admin:" + email)
    elif not check_password(payload.password):
        raise HTTPException(401, "Incorrect administrator password.")
    with _lock:
        _attempts.pop(host, None)
    if member:
        admins.log_activity("admin", member.id, member.name, "Signed in")
    else:
        admins.log_activity("owner", None, OWNER_NAME, "Signed in")
    response.set_cookie(COOKIE_NAME, issue_session(member), max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.post("/logout", dependencies=[Depends(require_admin)])
def logout(request: Request, response: Response):
    audit(request, "Signed out")
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"authenticated": False}


@router.get("/session")
def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": is_admin(request)}
