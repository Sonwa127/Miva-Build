"""Collaborator admin logins (owner only) and the activity log (every admin)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from archive import accounts, admins

from ..auth import audit, identity, require_admin, require_owner

api_router = APIRouter(prefix="/api/admin", tags=["Administration"])
page_router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))


class NewAdmin(BaseModel):
    email: str | None = Field(None, max_length=254)
    account_id: int | None = None
    name: str | None = Field(None, max_length=60)


def _public(a: admins.Admin) -> dict:
    return {"id": a.id, "name": a.name, "email": a.email, "disabled": a.disabled,
            "created_at": a.created_at, "last_login_at": a.last_login_at}


def _page(request: Request, name: str, **context):
    who = identity(request)
    response = templates.TemplateResponse(request=request, name=name, context={
        "active_page": "admin", "who": who.name, "is_owner": who.is_owner, **context})
    response.headers["Cache-Control"] = "no-store"
    return response


# ------------------------------------------------------------------------- pages
@page_router.get("/admin/team")
def team_page(request: Request):
    who = identity(request)
    if not who:
        return RedirectResponse("/admin/login", status_code=303)
    if not who.is_owner:
        return RedirectResponse("/admin", status_code=303)
    return _page(request, "admin_team.html")


@page_router.get("/admin/activity")
def activity_page(request: Request):
    if not identity(request):
        return RedirectResponse("/admin/login", status_code=303)
    return _page(request, "admin_activity.html")


# ----------------------------------------------------------------- collaborators
@api_router.get("/team", dependencies=[Depends(require_owner)])
def list_team():
    return [_public(a) for a in admins.list_admins()]


@api_router.post("/team", dependencies=[Depends(require_owner)])
def make_member(payload: NewAdmin, request: Request):
    """Give an existing student account admin rights (they sign up first with the cohort code)."""
    if payload.account_id is not None:
        account = accounts.get_account(payload.account_id)
    else:
        email = accounts.normalize_email(payload.email)
        if not email:
            raise HTTPException(422, "That does not look like an email address.")
        account = accounts.get_account_by_email(email)
    if not account:
        raise HTTPException(422, "No student account with that email. They need to sign up first with the cohort code.")
    if payload.name and not admins.clean_name(payload.name):
        raise HTTPException(422, "Enter a name up to 60 characters.")
    try:
        member = admins.make_admin(account.id, payload.name)
    except ValueError as problem:
        raise HTTPException(409 if "already" in str(problem) else 422, str(problem))
    audit(request, "Made someone an admin", f"{member.name} ({member.email})")
    return _public(member)


@api_router.delete("/team/{member_id}", dependencies=[Depends(require_owner)])
def remove_member(member_id: int, request: Request):
    member = admins.get_admin(member_id)
    if not member:
        raise HTTPException(404, "No such admin.")
    admins.remove_admin(member_id)
    audit(request, "Removed an admin", f"{member.name} ({member.email})")
    return {"removed": True}


# ---------------------------------------------------------------------- activity
@api_router.get("/activity", dependencies=[Depends(require_admin)])
def activity(limit: int = 200, actor: str = ""):
    return {"events": admins.list_activity(limit, actor or None), "people": admins.activity_actors()}


@api_router.get("/me", dependencies=[Depends(require_admin)])
def me(request: Request):
    who = identity(request)
    return {"name": who.name, "is_owner": who.is_owner}
