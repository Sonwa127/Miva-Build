"""Student signup, login, logout and password reset pages (plain HTML forms, no JavaScript needed)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from archive import accounts, config

from ..auth import check_origin

router = APIRouter(tags=["Student accounts"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))


def _page(request: Request, name: str, status: int = 200, **context):
    response = templates.TemplateResponse(request=request, name=name, context=context, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _message(request: Request, title: str, text: str, status: int = 200, link: tuple[str, str] | None = None):
    return _page(request, "account_message.html", status, title=title, text=text, link=link)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _start_session(response, request: Request, account: accounts.Account):
    response.set_cookie(accounts.COOKIE_NAME, accounts.issue_session(account), max_age=accounts.SESSION_SECONDS,
                        httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/")
    return response


# ---------------------------------------------------------------------------- login
@router.get("/login")
def login_page(request: Request, next: str = "/", notice: str = ""):
    if accounts.account_from_cookie(request.cookies.get(accounts.COOKIE_NAME)):
        return RedirectResponse(accounts.safe_next(next), status_code=303)
    return _page(request, "account_login.html", next=accounts.safe_next(next), notice=notice, error=None, email="")


@router.post("/login")
def login_submit(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("/")):
    check_origin(request)
    next = accounts.safe_next(next)
    key = accounts.normalize_email(email) or email.strip().lower()[:100]
    if not (accounts.login_by_ip.hit(_client_ip(request)) and accounts.login_by_email.hit(key)):
        return _page(request, "account_login.html", 429, next=next, notice="", email=email[:254],
                     error="Too many attempts. Please wait 15 minutes and try again.")
    account = accounts.authenticate(email, password)
    if not account:
        return _page(request, "account_login.html", 401, next=next, notice="", email=email[:254],
                     error="Incorrect email or password.")
    accounts.login_by_email.reset(key)
    return _start_session(RedirectResponse(next, status_code=303), request, account)


@router.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    if request.method == "POST":
        check_origin(request)
    response = RedirectResponse("/login?notice=You+have+signed+out.", status_code=303)
    response.delete_cookie(accounts.COOKIE_NAME, path="/")
    return response


# --------------------------------------------------------------------------- signup
def _signup_page(request: Request, status: int = 200, error: str | None = None, email: str = ""):
    return _page(request, "account_signup.html", status, domains=config.ALLOWED_EMAIL_DOMAINS, error=error,
                 email=email[:254], min_length=accounts.MIN_PASSWORD, open=accounts.get_signup_code() is not None)


@router.get("/signup")
def signup_page(request: Request):
    return _signup_page(request)


@router.post("/signup")
def signup_submit(request: Request, email: str = Form(""), code: str = Form(""),
                  password: str = Form(""), confirmation: str = Form("")):
    check_origin(request)
    ip = _client_ip(request)
    if not accounts.wrong_code_by_ip.allowed(ip):
        return _signup_page(request, 429, "Too many wrong codes from this network. Try again in an hour.", email)
    if accounts.get_signup_code() is None:
        return _signup_page(request, 403, "Signup is closed right now. Ask your class admin.", email)
    if not accounts.signup_code_matches(code):
        accounts.wrong_code_by_ip.hit(ip)           # only wrong codes count, so a busy classroom is not locked out
        return _signup_page(request, 403, "That cohort code is not right. Check the code your class admin shared.", email)
    address = accounts.normalize_email(email)
    if not address:
        return _signup_page(request, 400, "That does not look like an email address.", email)
    if not accounts.domain_allowed(address):
        shown = ", ".join("@" + d for d in config.ALLOWED_EMAIL_DOMAINS)
        return _signup_page(request, 403, f"Please use your school email ({shown}).", email)
    if password != confirmation:
        return _signup_page(request, 400, "The two passwords do not match.", email)
    try:
        account = accounts.create_account(address, password)
    except ValueError as problem:
        return _signup_page(request, 400, str(problem), email)
    return _start_session(RedirectResponse("/", status_code=303), request, account)


# ------------------------------------------------------------------ set a password
@router.get("/verify")
def verify_page(request: Request, token: str = ""):
    info = accounts.peek_token(token)
    if not info:
        return _message(request, "This link no longer works",
                        "It may have expired or been used already. Ask your class admin for a new one.", 400, ("/login", "Back to sign in"))
    return _page(request, "account_setpassword.html", token=token, email=info["email"], purpose=info["purpose"],
                 error=None, min_length=accounts.MIN_PASSWORD)


@router.post("/verify")
def verify_submit(request: Request, token: str = Form(""), password: str = Form(""), confirmation: str = Form("")):
    check_origin(request)
    info = accounts.peek_token(token)
    if not info:
        return _message(request, "This link no longer works",
                        "It may have expired or been used already. Ask your class admin for a new one.", 400, ("/login", "Back to sign in"))

    def again(error: str):
        return _page(request, "account_setpassword.html", 400, token=token, email=info["email"],
                     purpose=info["purpose"], error=error, min_length=accounts.MIN_PASSWORD)

    if password != confirmation:
        return again("The two passwords do not match.")
    try:
        account = accounts.finish_with_password(token, password)
    except ValueError as problem:
        return again(str(problem))
    if not account:
        return _message(request, "This link no longer works",
                        "It may have expired or been used already. Ask your class admin for a new one.", 400, ("/login", "Back to sign in"))
    if account.disabled:
        return _message(request, "Account disabled", "This account has been disabled. Ask your class admin.", 403)
    return _start_session(RedirectResponse("/", status_code=303), request, account)


# --------------------------------------------------------------------- forgot password
@router.get("/forgot")
def forgot_page(request: Request):
    return _page(request, "account_forgot.html")
