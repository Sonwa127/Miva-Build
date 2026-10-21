"""Collaborator admin logins, admin sessions and the activity log. No web server needed."""
import time

import pytest

from api import activity as activity_labels
from api import auth
from archive import accounts, admins, config

PASSWORD = "a long collaborator password"


class FakeRequest:
    """Just enough of a request for the session helpers."""
    def __init__(self, cookie=None, method="GET"):
        self.cookies = {auth.COOKIE_NAME: cookie} if cookie else {}
        self.method = method
        self.headers = {}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ACCOUNTS_DB", tmp_path / "accounts.sqlite")
    monkeypatch.setattr(accounts, "PBKDF2_ROUNDS", 1000)
    monkeypatch.setattr(auth, "password_hash", lambda password, salt: __import__("hashlib").pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 1000).hex())
    auth.configure_admin("the main owner password")
    accounts.reset_rate_limits()
    return tmp_path


def make_member(email="lit@example.com", name="Litpathway", password=PASSWORD):
    """A classmate signs up as a student, then the owner makes them an admin."""
    account = accounts.create_account(email, password)
    return admins.make_admin(account.id, name)


# ----------------------------------------------------------------- collaborators
def test_student_becomes_admin_and_signs_in_with_the_same_login(db):
    member = make_member()
    assert member.name == "Litpathway" and member.email == "lit@example.com" and not member.disabled
    assert admins.authenticate_admin("LIT@example.com", PASSWORD).id == member.id
    assert accounts.authenticate("lit@example.com", PASSWORD).id == member.id        # still a student too
    assert admins.get_admin(member.id).last_login_at is not None


def test_wrong_unknown_and_non_admin_logins_all_fail(db):
    make_member()
    accounts.create_account("plain@school.edu.ng", "plain student pw 1")
    assert admins.authenticate_admin("lit@example.com", "wrong wrong wrong") is None
    assert admins.authenticate_admin("nobody@example.com", PASSWORD) is None
    assert admins.authenticate_admin(None, PASSWORD) is None
    assert admins.authenticate_admin("plain@school.edu.ng", "plain student pw 1") is None   # right password, no admin rights


def test_only_existing_enabled_accounts_can_be_made_admin(db):
    with pytest.raises(ValueError):
        admins.make_admin(999)
    account = accounts.create_account("lit@example.com", PASSWORD)
    accounts.set_disabled(account.id, True)
    with pytest.raises(ValueError):
        admins.make_admin(account.id)
    accounts.set_disabled(account.id, False)
    admins.make_admin(account.id)
    with pytest.raises(ValueError):
        admins.make_admin(account.id)                     # already an admin
    assert len(admins.list_admins()) == 1


def test_default_name_comes_from_the_email_and_names_are_cleaned(db):
    account = accounts.create_account("ada.obi@example.com", PASSWORD)
    assert admins.make_admin(account.id).name == "ada.obi"
    assert admins.clean_name("  Ada   Obi ") == "Ada Obi"
    assert admins.clean_name("") is None and admins.clean_name("x" * 61) is None
    assert admins.clean_name("bad\x00name") is None
    other = accounts.create_account("b@example.com", PASSWORD)
    with pytest.raises(ValueError):
        admins.make_admin(other.id, "x" * 61)


def test_removing_admin_rights_keeps_the_student_account(db):
    member = make_member()
    assert admins.remove_admin(member.id) and not admins.remove_admin(member.id)
    assert admins.authenticate_admin("lit@example.com", PASSWORD) is None
    assert accounts.authenticate("lit@example.com", PASSWORD) is not None


def test_deleting_the_student_account_removes_admin_rights(db):
    member = make_member()
    accounts.delete_account(member.id)
    assert admins.get_admin(member.id) is None and admins.list_admins() == []


def test_disabled_student_account_cannot_sign_in_as_admin(db):
    member = make_member()
    accounts.set_disabled(member.id, True)
    assert admins.authenticate_admin("lit@example.com", PASSWORD) is None
    assert admins.get_admin(member.id).disabled
    accounts.set_disabled(member.id, False)
    assert admins.authenticate_admin("lit@example.com", PASSWORD) is not None


# ---------------------------------------------------------------------- sessions
def test_owner_session(db):
    who = auth.identity(FakeRequest(auth.issue_session()))
    assert who.is_owner and who.name == "Owner" and who.id is None
    assert auth.is_admin(FakeRequest(auth.issue_session()))


def test_collaborator_session(db):
    member = make_member()
    who = auth.identity(FakeRequest(auth.issue_session(member)))
    assert not who.is_owner and who.id == member.id and who.name == "Litpathway" and who.email == "lit@example.com"


def test_no_cookie_or_junk_cookie_is_nobody(db):
    for cookie in [None, "", "junk", "a.b.c", "1.2.3.4.5", "x" * 400, "9999999999.abc.def"]:
        assert auth.identity(FakeRequest(cookie)) is None, cookie


def test_tampering_is_detected(db):
    member = make_member()
    token = auth.issue_session(member)
    expiry, nonce, admin_id, version, signature = token.split(".")
    forged_id = ".".join([expiry, nonce, str(int(admin_id) + 1), version, signature])
    forged_version = ".".join([expiry, nonce, admin_id, str(int(version) + 1), signature])
    later = ".".join([str(int(expiry) + 99999), nonce, admin_id, version, signature])
    for forged in (forged_id, forged_version, later):
        assert auth.identity(FakeRequest(forged)) is None
    # A collaborator cannot turn their cookie into an owner cookie by dropping parts.
    assert auth.identity(FakeRequest(".".join([expiry, nonce, signature]))) is None


def test_expired_session(db, monkeypatch):
    token = auth.issue_session(make_member())
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + auth.SESSION_SECONDS + 5)
    assert auth.identity(FakeRequest(token)) is None


def test_disabling_resetting_removing_or_deleting_ends_admin_sessions(db):
    member = make_member()
    token = auth.issue_session(member)
    assert auth.identity(FakeRequest(token))
    accounts.set_disabled(member.id, True)                         # disabling the student account
    assert auth.identity(FakeRequest(token)) is None
    accounts.set_disabled(member.id, False)
    assert auth.identity(FakeRequest(token)) is None               # the old cookie stays dead after re-enabling

    fresh = auth.issue_session(admins.get_admin(member.id))
    assert auth.identity(FakeRequest(fresh))
    reset = accounts.issue_token("lit@example.com", "reset")       # the student resets their password
    accounts.finish_with_password(reset, "a brand new passphrase")
    assert auth.identity(FakeRequest(fresh)) is None

    again = auth.issue_session(admins.get_admin(member.id))
    assert auth.identity(FakeRequest(again))
    admins.remove_admin(member.id)                                 # admin rights taken away
    assert auth.identity(FakeRequest(again)) is None
    admins.make_admin(member.id)
    last = auth.issue_session(admins.get_admin(member.id))
    accounts.delete_account(member.id)
    assert auth.identity(FakeRequest(last)) is None


def test_owner_password_change_signs_everyone_out(db):
    member = make_member()
    owner_token, member_token = auth.issue_session(), auth.issue_session(member)
    auth.configure_admin("a different owner password")
    assert auth.identity(FakeRequest(owner_token)) is None and auth.identity(FakeRequest(member_token)) is None


def test_only_the_owner_passes_require_owner(db):
    member = make_member()
    auth.require_owner(FakeRequest(auth.issue_session()))
    auth.require_admin(FakeRequest(auth.issue_session(member)))        # collaborators are admins
    with pytest.raises(auth.HTTPException) as error:
        auth.require_owner(FakeRequest(auth.issue_session(member)))
    assert error.value.status_code == 403
    with pytest.raises(auth.HTTPException) as error:
        auth.require_owner(FakeRequest())
    assert error.value.status_code == 401


# ------------------------------------------------------------------------ activity
def test_activity_newest_first_and_filter(db):
    admins.log_activity("owner", None, "Owner", "Signed in")
    admins.log_activity("admin", 1, "Litpathway", "Uploaded a PDF", "/api/documents/upload")
    admins.log_activity("admin", 1, "Litpathway", "Added a course", "/api/courses")
    events = admins.list_activity()
    assert [e["action"] for e in events] == ["Added a course", "Uploaded a PDF", "Signed in"]
    assert [e["action"] for e in admins.list_activity(actor="Owner")] == ["Signed in"]
    assert len(admins.list_activity(limit=1)) == 1
    assert admins.activity_actors() == ["Litpathway", "Owner"]
    assert events[0]["at"].endswith("Z")


def test_activity_is_capped(db, monkeypatch):
    monkeypatch.setattr(admins, "MAX_ACTIVITY_ROWS", 5)
    for number in range(12):
        admins.log_activity("owner", None, "Owner", f"Action {number}")
    events = admins.list_activity()
    assert len(events) == 5 and events[0]["action"] == "Action 11"


def test_logging_never_breaks_the_admin_action(db, monkeypatch):
    monkeypatch.setattr(config, "ACCOUNTS_DB", db)         # a folder, not a database file
    admins.log_activity("owner", None, "Owner", "Anything")  # must not raise


def test_audit_names_the_signed_in_person(db):
    member = make_member()
    auth.audit(FakeRequest(auth.issue_session(member)), "Added a course", "/api/courses")
    auth.audit(FakeRequest(auth.issue_session()), "Deleted a course")
    auth.audit(FakeRequest(), "Should not appear")
    assert [(e["actor_name"], e["action"]) for e in admins.list_activity()] == [
        ("Owner", "Deleted a course"), ("Litpathway", "Added a course")]


def test_only_library_changes_get_labels():
    d = activity_labels.describe
    assert d("POST", "/api/documents/upload") == "Uploaded a PDF"
    assert d("DELETE", "/api/documents/abc123") == "Removed a PDF"
    assert d("PATCH", "/api/documents/abc/placement") == "Changed where a PDF is placed"
    assert d("POST", "/api/resources") == "Added a video or link"
    assert d("DELETE", "/api/courses/5/weeks/2") == "Deleted a course week"
    assert d("POST", "/api/study/flashcards/generate") == "Generated flashcards"
    # Not logged: reading, students asking questions, flashcard reviews, odd paths.
    for method, path in [("GET", "/api/documents"), ("POST", "/api/qa/ask"), ("POST", "/api/qa/feedback"),
                         ("POST", "/api/study/flashcards/review"), ("POST", "/api/study/quizzes/3/submit"),
                         ("DELETE", "/api/documents/abc/extra"), ("POST", "/api/evaluation/evaluate"),
                         ("DELETE", "/api/documents")]:
        assert d(method, path) is None, (method, path)


def test_disabled_flag_alone_blocks_a_session(db):
    # Even if the session version were not bumped, a disabled collaborator's cookie must fail.
    member = make_member()
    token = auth.issue_session(member)
    with accounts._db() as c:
        c.execute("UPDATE accounts SET disabled=1 WHERE id=?", (member.id,))
    assert auth.identity(FakeRequest(token)) is None
