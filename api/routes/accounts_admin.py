"""Administrator tools for student accounts: cohort code, one-time links, disable, delete."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from archive import accounts, admins, config

from ..auth import audit, identity, require_admin

api_router = APIRouter(prefix="/api/admin/users", tags=["Administration"], dependencies=[Depends(require_admin)])
page_router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))


class InviteInput(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


def _public(a: accounts.Account) -> dict:
    return {"id": a.id, "email": a.email, "disabled": a.disabled, "admin": admins.is_admin_account(a.id),
            "created_at": a.created_at, "last_login_at": a.last_login_at}


@page_router.get("/admin/users")
def users_page(request: Request):
    who = identity(request)
    if not who:
        return RedirectResponse("/admin/login", status_code=303)
    response = templates.TemplateResponse(request=request, name="admin_users.html", context={
        "active_page": "admin", "who": who.name, "is_owner": who.is_owner, "domains": config.ALLOWED_EMAIL_DOMAINS, "login_required": config.REQUIRE_LOGIN,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@api_router.get("")
def list_users():
    return [_public(a) for a in accounts.list_accounts()]


def _link(request: Request, email: str, purpose: str) -> dict:
    token = accounts.issue_token(email, purpose)
    base = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    return {"email": email, "link": f"{base}/verify?token={token}", "expires_in_hours": accounts.LINK_TTL_SECONDS // 3600}


@api_router.get("/code")
def get_code():
    return {"code": accounts.get_signup_code()}


@api_router.post("/code")
def make_code(request: Request):
    """Create a new cohort code. The old one stops working at once."""
    audit(request, "Made a new cohort code")
    return {"code": accounts.new_signup_code()}


@api_router.delete("/code")
def close_signup(request: Request):
    audit(request, "Closed signup")
    accounts.clear_signup_code()
    return {"code": None}


@api_router.post("/invite")
def invite(payload: InviteInput, request: Request):
    """One-time sign-up link for any address, e.g. a classmate whose school email is not working."""
    email = accounts.normalize_email(payload.email)
    if not email:
        raise HTTPException(422, "That does not look like an email address.")
    if accounts.get_account_by_email(email):
        raise HTTPException(409, "That email already has an account. Use Reset link instead.")
    audit(request, "Made a sign-up link", email)
    return _link(request, email, "signup")


@api_router.post("/{account_id}/reset-link")
def reset_link(account_id: int, request: Request):
    """One-time link for a student who forgot their password. Send it to them yourself."""
    account = accounts.get_account(account_id)
    if not account:
        raise HTTPException(404, "No such account.")
    audit(request, "Made a password reset link", account.email)
    return _link(request, account.email, "reset")


@api_router.post("/{account_id}/disable")
def disable(account_id: int, request: Request):
    account = accounts.get_account(account_id)
    if not account or not accounts.set_disabled(account_id, True):
        raise HTTPException(404, "No such account.")
    audit(request, "Disabled a student account", account.email)
    return {"disabled": True}


@api_router.post("/{account_id}/enable")
def enable(account_id: int, request: Request):
    account = accounts.get_account(account_id)
    if not account or not accounts.set_disabled(account_id, False):
        raise HTTPException(404, "No such account.")
    audit(request, "Re-enabled a student account", account.email)
    return {"disabled": False}


@api_router.delete("/{account_id}")
def remove(account_id: int, request: Request):
    account = accounts.get_account(account_id)
    if not account or not accounts.delete_account(account_id):
        raise HTTPException(404, "No such account.")
    audit(request, "Deleted a student account", account.email)
    return {"deleted": True}
