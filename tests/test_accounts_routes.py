"""Student login pages and the login gate, tested through the real web app."""
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.auth import configure_admin
from api.gate import is_public_path
from archive import accounts, config

PASSWORD = "correct horse battery"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ACCOUNTS_DB", tmp_path / "accounts.sqlite")
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ("school.edu.ng",))
    monkeypatch.setattr(config, "REQUIRE_LOGIN", True)
    monkeypatch.setattr(config, "PUBLIC_URL", "http://testserver")
    monkeypatch.setattr(accounts, "PBKDF2_ROUNDS", 1000)
    accounts.reset_rate_limits()
    code = accounts.new_signup_code()
    client = TestClient(app)
    yield client, code
    client.close()
    accounts.reset_rate_limits()


def form(code, email="ada@school.edu.ng", password=PASSWORD, confirmation=None):
    return {"email": email, "code": code, "password": password,
            "confirmation": password if confirmation is None else confirmation}


def sign_up(client, code, email="ada@school.edu.ng", password=PASSWORD):
    response = client.post("/signup", data=form(code, email, password), follow_redirects=False)
    assert response.status_code == 303, response.text
    return response


def admin_sign_in(client):
    configure_admin("a-long-test-password-2026")
    assert client.post("/api/admin/login", json={"password": "a-long-test-password-2026"}).status_code == 200


def test_public_paths():
    for path in ["/login", "/signup", "/verify", "/forgot", "/logout", "/static/css/app.css", "/admin",
                 "/admin/login", "/admin/users", "/api/admin/login", "/api/admin/users"]:
        assert is_public_path(path), path
    for path in ["/", "/ask", "/courses", "/resources", "/study", "/quizzes", "/api/qa", "/api/documents", "/docs",
                 "/loginx", "/administrator", "/api/administrator", "/staticfiles/x"]:
        assert not is_public_path(path), path


def test_signed_out_visitors_are_sent_to_login_and_apis_refuse(site):
    client, _ = site
    response = client.get("/ask?course_id=3", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login?next=%2Fask%3Fcourse_id%3D3"
    assert client.get("/api/courses", follow_redirects=False).status_code == 401
    assert client.post("/api/qa/ask", json={}, follow_redirects=False).status_code == 401
    for path in ["/login", "/signup", "/forgot", "/static/css/app.css"]:
        assert client.get(path, follow_redirects=False).status_code == 200, path


def test_gate_is_off_unless_enabled(site, monkeypatch):
    client, _ = site
    monkeypatch.setattr(config, "REQUIRE_LOGIN", False)
    assert client.get("/docs", follow_redirects=False).status_code == 200


def test_signup_with_cohort_code_end_to_end(site):
    client, code = site
    page = client.get("/signup")
    assert page.status_code == 200 and 'name="code"' in page.text
    done = client.post("/signup", data=form(code.lower(), "Ada@School.edu.ng"), follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == "/"
    assert accounts.COOKIE_NAME in done.headers["set-cookie"] and "HttpOnly" in done.headers["set-cookie"]
    assert accounts.get_account_by_email("ada@school.edu.ng") is not None
    assert client.get("/docs", follow_redirects=False).status_code == 200      # signed in: the gate lets them through


def test_wrong_code_domain_password_problems_create_nothing(site):
    client, code = site
    wrong = client.post("/signup", data=form("AAAA-BBBB-CCCC"))
    assert wrong.status_code == 403 and "cohort code" in wrong.text
    assert client.post("/signup", data=form("")).status_code == 403
    assert client.post("/signup", data=form(code, "ada@gmail.com")).status_code == 403
    assert client.post("/signup", data=form(code, "nonsense")).status_code == 400
    mismatch = client.post("/signup", data=form(code, confirmation="something else entirely"))
    assert mismatch.status_code == 400 and "do not match" in mismatch.text
    weak = client.post("/signup", data=form(code, password="short"))
    assert weak.status_code == 400 and "at least" in weak.text
    assert accounts.list_accounts() == []


def test_signup_is_closed_when_there_is_no_code(site):
    client, code = site
    accounts.clear_signup_code()
    page = client.get("/signup")
    assert "closed" in page.text and 'name="code"' not in page.text
    assert client.post("/signup", data=form(code)).status_code == 403
    assert accounts.list_accounts() == []


def test_old_code_stops_working_after_a_new_one_is_made(site):
    client, code = site
    accounts.new_signup_code()
    assert client.post("/signup", data=form(code)).status_code == 403


def test_duplicate_signup_does_not_touch_the_existing_account(site):
    client, code = site
    sign_up(client, code)
    client.cookies.clear()
    again = client.post("/signup", data=form(code, password="attacker chosen password"))
    assert again.status_code == 400 and "already exists" in again.text
    assert accounts.authenticate("ada@school.edu.ng", PASSWORD)


def test_only_wrong_codes_are_rate_limited(site):
    client, code = site
    for _ in range(10):
        assert client.post("/signup", data=form("AAAA-BBBB-CCCC")).status_code == 403
    assert client.post("/signup", data=form("AAAA-BBBB-CCCC")).status_code == 429
    assert client.post("/signup", data=form(code)).status_code == 429          # even the right code waits out the lock
    accounts.reset_rate_limits()
    # A whole classroom on one Wi-Fi: correct signups never use up the allowance.
    for n in range(15):
        assert client.post("/signup", data=form(code, f"student{n}@school.edu.ng"), follow_redirects=False).status_code == 303
        client.cookies.clear()


def test_login_logout_and_wrong_password(site):
    client, code = site
    sign_up(client, code)
    client.cookies.clear()
    bad = client.post("/login", data={"email": "ada@school.edu.ng", "password": "wrong password here"})
    assert bad.status_code == 401 and "Incorrect email or password" in bad.text
    unknown = client.post("/login", data={"email": "nobody@school.edu.ng", "password": PASSWORD})
    assert unknown.status_code == 401 and "Incorrect email or password" in unknown.text   # same message
    good = client.post("/login", data={"email": "ADA@school.edu.ng", "password": PASSWORD, "next": "/ask"},
                       follow_redirects=False)
    assert good.status_code == 303 and good.headers["location"] == "/ask"
    assert client.get("/docs", follow_redirects=False).status_code == 200
    out = client.post("/logout", follow_redirects=False)
    assert out.status_code == 303 and "/login" in out.headers["location"]
    assert client.get("/docs", follow_redirects=False).status_code == 303


def test_login_cannot_redirect_to_other_sites(site):
    client, code = site
    sign_up(client, code)
    client.cookies.clear()
    for target in ["https://evil.example", "//evil.example", "/\\evil.example"]:
        response = client.post("/login", data={"email": "ada@school.edu.ng", "password": PASSWORD, "next": target},
                               follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/", target
        client.cookies.clear()


def test_too_many_wrong_passwords_lock_the_account_for_a_while(site):
    client, code = site
    sign_up(client, code)
    client.cookies.clear()
    for _ in range(8):
        assert client.post("/login", data={"email": "ada@school.edu.ng", "password": "wrong password here"}).status_code == 401
    assert client.post("/login", data={"email": "ada@school.edu.ng", "password": PASSWORD}).status_code == 429


def test_forgot_page_tells_students_to_ask_the_admin(site):
    client, _ = site
    page = client.get("/forgot")
    assert page.status_code == 200 and "class admin" in page.text and "<form" not in page.text


def test_admin_reset_link_flow_signs_out_old_sessions(site):
    client, code = site
    sign_up(client, code)
    old_cookie = client.cookies.get(accounts.COOKIE_NAME)
    with TestClient(app) as admin:
        admin_sign_in(admin)
        user_id = admin.get("/api/admin/users").json()[0]["id"]
        link = admin.post(f"/api/admin/users/{user_id}/reset-link").json()["link"]
    token = link.split("token=")[1]
    assert client.get(f"/verify?token={token}").status_code == 200
    new_password = "a brand new passphrase"
    response = client.post("/verify", data={"token": token, "password": new_password, "confirmation": new_password},
                           follow_redirects=False)
    assert response.status_code == 303
    assert client.get(f"/verify?token={token}").status_code == 400            # works once
    client.cookies.clear()
    old_session = {"cookie": f"{accounts.COOKIE_NAME}={old_cookie}"}
    assert client.get("/docs", headers=old_session, follow_redirects=False).status_code == 303   # old session is dead
    assert client.post("/login", data={"email": "ada@school.edu.ng", "password": PASSWORD}).status_code == 401
    assert client.post("/login", data={"email": "ada@school.edu.ng", "password": new_password},
                       follow_redirects=False).status_code == 303


def test_cross_site_form_posts_are_refused(site):
    client, code = site
    for path, data in [("/login", {"email": "a@school.edu.ng", "password": "x"}), ("/signup", form(code)),
                       ("/verify", {"token": "x" * 30, "password": "x", "confirmation": "x"})]:
        response = client.post(path, data=data, headers={"origin": "https://evil.example"})
        assert response.status_code == 403, path
    assert accounts.list_accounts() == []


def test_pages_do_not_get_cached(site):
    client, _ = site
    assert "no-store" in client.get("/login").headers["cache-control"]
    assert "no-store" in client.get("/signup").headers["cache-control"]


def test_admin_pages_need_the_admin_login(site):
    client, code = site
    assert client.get("/admin/users", follow_redirects=False).status_code == 303
    for method, path in [("get", "/api/admin/users"), ("get", "/api/admin/users/code"), ("post", "/api/admin/users/code"),
                         ("delete", "/api/admin/users/code"), ("post", "/api/admin/users/invite"),
                         ("post", "/api/admin/users/1/reset-link")]:
        assert getattr(client, method)(path).status_code == 401, path
    assert accounts.signup_code_matches(code)                                   # nothing changed


def test_a_student_login_does_not_open_the_admin_tools(site):
    client, code = site
    sign_up(client, code)
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/admin/users/code").status_code == 401


def test_admin_manages_the_code(site):
    client, code = site
    admin_sign_in(client)
    assert client.get("/admin/users").status_code == 200
    assert client.get("/api/admin/users/code").json() == {"code": code}
    new = client.post("/api/admin/users/code").json()["code"]
    assert new != code and accounts.signup_code_matches(new) and not accounts.signup_code_matches(code)
    assert client.delete("/api/admin/users/code").json() == {"code": None}
    assert client.get("/api/admin/users/code").json() == {"code": None}


def test_admin_links_and_account_management(site):
    client, code = site
    admin_sign_in(client)
    invited = client.post("/api/admin/users/invite", json={"email": "Friend@Gmail.com"})
    assert invited.status_code == 200
    body = invited.json()
    assert body["email"] == "friend@gmail.com" and "/verify?token=" in body["link"] and "emailed" not in body
    assert client.post("/api/admin/users/invite", json={"email": "nonsense"}).status_code == 422

    # The invited classmate (a separate browser) uses the link even though gmail.com is not a school domain.
    with TestClient(app) as friend:
        token = body["link"].split("token=")[1]
        done = friend.post("/verify", data={"token": token, "password": PASSWORD, "confirmation": PASSWORD},
                           follow_redirects=False)
        assert done.status_code == 303
        assert friend.get("/docs", follow_redirects=False).status_code == 200
        assert client.post("/api/admin/users/invite", json={"email": "friend@gmail.com"}).status_code == 409

        users = client.get("/api/admin/users").json()
        assert [u["email"] for u in users] == ["friend@gmail.com"] and users[0]["disabled"] is False
        user_id = users[0]["id"]
        assert client.post(f"/api/admin/users/{user_id}/disable").status_code == 200
        assert friend.get("/docs", follow_redirects=False).status_code == 303   # signed out immediately
        assert friend.post("/login", data={"email": "friend@gmail.com", "password": PASSWORD}).status_code == 401
        assert client.post(f"/api/admin/users/{user_id}/enable").status_code == 200
        assert friend.post("/login", data={"email": "friend@gmail.com", "password": PASSWORD},
                           follow_redirects=False).status_code == 303
    assert client.delete(f"/api/admin/users/{user_id}").status_code == 200
    assert client.delete(f"/api/admin/users/{user_id}").status_code == 404
    assert client.post("/api/admin/users/999/disable").status_code == 404
    assert client.post("/api/admin/users/999/reset-link").status_code == 404


def test_admin_stays_signed_in_through_the_gate(site):
    client, _ = site
    admin_sign_in(client)
    assert client.get("/docs", follow_redirects=False).status_code == 200      # the admin needs no student account
