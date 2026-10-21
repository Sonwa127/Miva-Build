"""Collaborator logins, owner-only team management and the activity log, through the real web app."""
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.auth import configure_admin
from api.routes import admin
from archive import accounts, admins, analytics, config, courses, summaries, glossary

OWNER_PASSWORD = "a-long-owner-password-2026"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ACCOUNTS_DB", tmp_path / "accounts.sqlite")
    monkeypatch.setattr(config, "APP_DB", tmp_path / "app.sqlite")
    monkeypatch.setattr(config, "REGISTRY_DB", tmp_path / "registry.sqlite")
    monkeypatch.setattr(config, "REQUIRE_LOGIN", False)
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ())
    monkeypatch.setattr(courses, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(analytics, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(summaries, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(glossary, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(accounts, "PBKDF2_ROUNDS", 1000)
    admin._attempts.clear()
    accounts.reset_rate_limits()
    configure_admin(OWNER_PASSWORD)
    client = TestClient(app)
    yield client
    client.close()
    admin._attempts.clear()
    accounts.reset_rate_limits()


def owner_sign_in(client):
    assert client.post("/api/admin/login", json={"password": OWNER_PASSWORD}).status_code == 200


def add_member(owner, name="Litpathway", email="lit@example.com", password="lit student password"):
    """The classmate signs up as a student, then the owner makes them an admin."""
    accounts.create_account(email, password)
    response = owner.post("/api/admin/team", json={"email": email, "name": name})
    assert response.status_code == 200, response.text
    return {**response.json(), "password": password}


def member_client(email, password):
    client = TestClient(app)
    response = client.post("/api/admin/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


def events(client, **params):
    return client.get("/api/admin/activity", params=params).json()["events"]


def test_owner_makes_a_student_an_admin_who_signs_in_with_the_same_login(site):
    owner_sign_in(site)
    member = add_member(site)
    assert member["name"] == "Litpathway" and "password" in member and "hash" not in str(member).lower()
    with member_client("LIT@example.com", member["password"]) as lit:
        assert lit.get("/api/admin/me").json() == {"name": "Litpathway", "is_owner": False}
        assert lit.get("/admin").status_code == 200
        assert lit.get("/api/admin/users").status_code == 200           # student accounts: full access
        assert lit.post("/api/admin/users/code").status_code == 200      # cohort code: full access
        assert site.get("/api/admin/me").json() == {"name": "Owner", "is_owner": True}
    student = TestClient(app)                                           # and as a student they still sign in normally
    assert student.post("/login", data={"email": "lit@example.com", "password": member["password"]},
                        follow_redirects=False).status_code == 303


def test_make_admin_from_the_student_list_and_checks(site):
    owner_sign_in(site)
    account = accounts.create_account("ada@school.edu.ng", "ada student password")
    assert site.get("/api/admin/users").json()[0]["admin"] is False
    made = site.post("/api/admin/team", json={"account_id": account.id})
    assert made.status_code == 200 and made.json()["name"] == "ada"      # default name from the email
    assert site.get("/api/admin/users").json()[0]["admin"] is True
    assert site.post("/api/admin/team", json={"account_id": account.id}).status_code == 409
    assert site.post("/api/admin/team", json={"email": "nobody@school.edu.ng"}).status_code == 422
    assert site.post("/api/admin/team", json={"email": "nonsense"}).status_code == 422
    assert site.post("/api/admin/team", json={"account_id": 999}).status_code == 422
    other = accounts.create_account("b@school.edu.ng", "b student password 1")
    assert site.post("/api/admin/team", json={"account_id": other.id, "name": "x" * 61}).status_code == 422
    listing = site.get("/api/admin/team").json()
    assert [m["email"] for m in listing] == ["ada@school.edu.ng"] and "password" not in str(listing)
    accounts.set_disabled(other.id, True)
    assert site.post("/api/admin/team", json={"account_id": other.id}).status_code == 422


def test_a_student_who_is_not_an_admin_cannot_sign_in_to_admin(site):
    accounts.create_account("plain@school.edu.ng", "plain student password")
    with TestClient(app) as stranger:
        response = stranger.post("/api/admin/login", json={"email": "plain@school.edu.ng", "password": "plain student password"})
        assert response.status_code == 401 and response.json()["detail"] == "Incorrect email or password."
        assert stranger.get("/api/admin/me").status_code == 401


def test_collaborators_cannot_manage_admins(site):
    owner_sign_in(site)
    member = add_member(site)
    friend = accounts.create_account("friend@example.com", "friend student password")
    with member_client("lit@example.com", member["password"]) as lit:
        assert lit.get("/api/admin/team").status_code == 403
        assert lit.post("/api/admin/team", json={"account_id": friend.id}).status_code == 403
        assert lit.delete(f"/api/admin/team/{member['id']}").status_code == 403
        assert lit.get("/admin/team", follow_redirects=False).headers["location"] == "/admin"
    assert [a.email for a in admins.list_admins()] == ["lit@example.com"]


def test_signed_out_and_student_visitors_get_nothing(site):
    for path in ["/api/admin/team", "/api/admin/activity", "/api/admin/me"]:
        assert site.get(path).status_code == 401, path
    assert site.post("/api/admin/team", json={"email": "x@example.com"}).status_code == 401
    for path in ["/admin/team", "/admin/activity"]:
        assert site.get(path, follow_redirects=False).headers["location"] == "/admin/login", path
    accounts.new_signup_code()
    code = accounts.get_signup_code()
    student = site.post("/signup", data={"email": "s@school.edu.ng", "code": code, "password": "student password 1",
                                         "confirmation": "student password 1"}, follow_redirects=False)
    assert student.status_code == 303                                  # a student is signed in now
    assert site.get("/api/admin/activity").status_code == 401
    assert site.get("/api/admin/team").status_code == 401


def test_wrong_logins_fail_the_same_way(site):
    owner_sign_in(site)
    member = add_member(site)
    with TestClient(app) as stranger:
        wrong = stranger.post("/api/admin/login", json={"email": "lit@example.com", "password": "wrong wrong wrong"})
        unknown = stranger.post("/api/admin/login", json={"email": "nobody@example.com", "password": member["password"]})
        assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
        assert stranger.post("/api/admin/login", json={"password": member["password"]}).status_code == 401    # not the owner password
        assert stranger.post("/api/admin/login", json={"email": "lit@example.com", "password": OWNER_PASSWORD}).status_code == 401


def test_removing_admin_rights_locks_them_out_at_once(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        assert lit.get("/api/admin/activity").status_code == 200
        assert site.delete(f"/api/admin/team/{member['id']}").status_code == 200
        assert lit.get("/api/admin/activity").status_code == 401
        assert lit.get("/admin", follow_redirects=False).status_code == 303
        assert lit.post("/api/admin/login", json={"email": "lit@example.com", "password": member["password"]}).status_code == 401
    assert accounts.authenticate("lit@example.com", member["password"]) is not None      # still a student
    assert site.delete(f"/api/admin/team/{member['id']}").status_code == 404


def test_disabling_the_student_account_also_locks_the_admin_out(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        assert site.post(f"/api/admin/users/{member['id']}/disable").status_code == 200
        assert lit.get("/api/admin/activity").status_code == 401
        assert lit.post("/api/admin/login", json={"email": "lit@example.com", "password": member["password"]}).status_code == 401
        assert site.post(f"/api/admin/users/{member['id']}/enable").status_code == 200
        assert lit.get("/api/admin/activity").status_code == 401         # the old session stays dead
    with member_client("lit@example.com", member["password"]) as again:
        assert again.get("/api/admin/activity").status_code == 200


def test_resetting_the_students_password_ends_their_admin_session(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        link = site.post(f"/api/admin/users/{member['id']}/reset-link").json()["link"]
        token = link.split("token=")[1]
        done = TestClient(app).post("/verify", data={"token": token, "password": "a brand new passphrase",
                                                     "confirmation": "a brand new passphrase"}, follow_redirects=False)
        assert done.status_code == 303
        assert lit.get("/api/admin/activity").status_code == 401
    with member_client("lit@example.com", "a brand new passphrase") as again:
        assert again.get("/api/admin/activity").status_code == 200


def test_deleting_the_student_account_removes_admin_access(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        assert site.delete(f"/api/admin/users/{member['id']}").status_code == 200
        assert lit.get("/api/admin/activity").status_code == 401
    assert site.get("/api/admin/team").json() == []


def test_activity_log_names_who_did_what(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        made = lit.post("/api/courses", json={"code": "PHY 101", "name": "Mechanics"})
        assert made.status_code == 201
        assert lit.delete(f"/api/courses/{made.json()['id']}").status_code == 204
        lit.post("/api/admin/users/code")
        log = events(lit)
    actions = [(e["actor_name"], e["action"]) for e in log]
    assert ("Litpathway", "Added a course") in actions
    assert ("Litpathway", "Deleted a course") in actions
    assert ("Litpathway", "Made a new cohort code") in actions
    assert ("Litpathway", "Signed in") in actions and ("Owner", "Signed in") in actions
    assert ("Owner", "Made someone an admin") in actions
    assert log[0]["at"] >= log[-1]["at"]
    assert [e["action"] for e in events(site, actor="Owner")] == ["Made someone an admin", "Signed in"]
    assert site.get("/api/admin/activity").json()["people"] == ["Litpathway", "Owner"]


def test_failed_and_unauthorised_requests_are_not_recorded(site):
    owner_sign_in(site)
    before = len(events(site))
    assert site.post("/api/courses", json={"name": "No code"}).status_code == 422         # invalid
    with TestClient(app) as stranger:
        assert stranger.post("/api/courses", json={"code": "X 1", "name": "Nope"}).status_code == 401
    assert len(events(site)) == before
    assert courses.get_course("X 1") is None


def test_student_account_actions_are_logged_with_the_students_email(site):
    owner_sign_in(site)
    accounts.create_account("ada@school.edu.ng", "student password 1")
    user_id = site.get("/api/admin/users").json()[0]["id"]
    site.post(f"/api/admin/users/{user_id}/reset-link")
    site.post(f"/api/admin/users/{user_id}/disable")
    site.post(f"/api/admin/users/{user_id}/enable")
    site.delete(f"/api/admin/users/{user_id}")
    site.post("/api/admin/users/invite", json={"email": "friend@gmail.com"})
    site.delete("/api/admin/users/code")
    log = {(e["action"], e["detail"]) for e in events(site)}
    assert ("Made a password reset link", "ada@school.edu.ng") in log
    assert ("Disabled a student account", "ada@school.edu.ng") in log
    assert ("Re-enabled a student account", "ada@school.edu.ng") in log
    assert ("Deleted a student account", "ada@school.edu.ng") in log
    assert ("Made a sign-up link", "friend@gmail.com") in log
    assert ("Closed signup", "") in log
    assert "token" not in str(log)                                    # links and passwords never go in the log


def test_passwords_never_appear_in_the_log(site):
    owner_sign_in(site)
    member = add_member(site, password="my own chosen password")
    with member_client("lit@example.com", "my own chosen password") as lit:
        lit.post("/api/courses", json={"code": "A 1", "name": "A"})
    assert "chosen password" not in str(events(site)) and OWNER_PASSWORD not in str(events(site))


def test_pages_render_for_the_right_people(site):
    owner_sign_in(site)
    member = add_member(site)
    assert "Admins" in site.get("/admin").text and "Activity log" in site.get("/admin").text
    assert site.get("/admin/team").status_code == 200 and site.get("/admin/activity").status_code == 200
    with member_client("lit@example.com", member["password"]) as lit:
        page = lit.get("/admin")
        assert "Litpathway" in page.text and 'href="/admin/team"' not in page.text
        assert lit.get("/admin/activity").status_code == 200
        assert "no-store" in lit.get("/admin/activity").headers["cache-control"]
    assert 'name="username"' in TestClient(app).get("/admin/login").text


def test_collaborator_passes_the_student_login_gate(site, monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_LOGIN", True)
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        assert lit.get("/courses", follow_redirects=False).status_code == 200
    with TestClient(app) as stranger:
        assert stranger.get("/courses", follow_redirects=False).status_code == 303


def test_collaborator_cannot_make_cross_site_changes(site):
    owner_sign_in(site)
    member = add_member(site)
    with member_client("lit@example.com", member["password"]) as lit:
        response = lit.post("/api/courses", json={"code": "A 1", "name": "A"}, headers={"origin": "https://evil.example"})
        assert response.status_code == 403
    assert site.post("/api/admin/team", json={"email": "lit@example.com"},
                     headers={"origin": "https://evil.example"}).status_code == 403
