"""Student account logic: emails, cohort code, links, passwords, sessions and rate limits. No web server needed."""
import sqlite3

import pytest

from archive import accounts, config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACCOUNTS_DB", tmp_path / "accounts.sqlite")
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ("school.edu.ng",))
    monkeypatch.setattr(accounts, "PBKDF2_ROUNDS", 1000)       # fast hashing for tests only
    accounts.reset_rate_limits()
    return tmp_path


def make_account(email="ada@school.edu.ng", password="correct horse battery"):
    token = accounts.issue_token(email, "signup")
    return accounts.finish_with_password(token, password)


# ------------------------------------------------------------------ email rules
def test_normalize_email():
    assert accounts.normalize_email("  Ada.Obi@School.edu.ng ") == "ada.obi@school.edu.ng"
    for bad in ["", None, "no-at-sign", "a@b", "a b@school.edu.ng", "a@@school.edu.ng", "@school.edu.ng",
                "a@school..edu.ng", "x" * 300 + "@school.edu.ng"]:
        assert accounts.normalize_email(bad) is None, bad


def test_domain_rule_allows_school_and_subdomains_but_not_lookalikes(db):
    assert accounts.domain_allowed("ada@school.edu.ng")
    assert accounts.domain_allowed("ada@students.school.edu.ng")
    assert not accounts.domain_allowed("ada@gmail.com")
    assert not accounts.domain_allowed("ada@evilschool.edu.ng")
    assert not accounts.domain_allowed("ada@school.edu.ng.evil.com")
    assert not accounts.domain_allowed("school.edu.ng@gmail.com")


def test_no_allowed_domains_means_any_email(db, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ())
    assert accounts.domain_allowed("ada@gmail.com")


# --------------------------------------------------------------------- passwords
def test_password_hash_roundtrip_and_failures(db):
    stored = accounts.hash_password("a good password")
    assert stored.startswith("pbkdf2_sha256$") and "a good password" not in stored
    assert accounts.verify_password("a good password", stored)
    assert not accounts.verify_password("another one", stored)
    assert accounts.hash_password("a good password") != stored          # random salt
    for junk in ["", "garbage", "md5$1$00$00", "pbkdf2_sha256$x$zz$zz"]:
        assert accounts.verify_password("a good password", junk) is False


def test_password_rules():
    assert accounts.password_problem("short") is not None
    assert accounts.password_problem("x" * 300) is not None
    assert accounts.password_problem("ada@school.edu.ng", "ada@school.edu.ng") is not None
    assert accounts.password_problem("ADA", "ada@school.edu.ng") is not None
    assert accounts.password_problem("a long enough passphrase", "ada@school.edu.ng") is None


# ----------------------------------------------------------- signup via one-time link
def test_signup_link_creates_account_and_can_sign_in(db):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    assert accounts.peek_token(token) == {"email": "ada@school.edu.ng", "purpose": "signup"}
    assert accounts.get_account_by_email("ada@school.edu.ng") is None     # nothing exists until a password is set
    account = accounts.finish_with_password(token, "correct horse battery")
    assert account.email == "ada@school.edu.ng" and not account.disabled
    assert accounts.authenticate("ADA@school.edu.ng", "correct horse battery").id == account.id
    assert accounts.authenticate("ada@school.edu.ng", "wrong password here") is None
    assert accounts.authenticate("nobody@school.edu.ng", "correct horse battery") is None
    assert accounts.authenticate(None, "x") is None


def test_link_works_only_once(db):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    assert accounts.finish_with_password(token, "correct horse battery") is not None
    assert accounts.finish_with_password(token, "something else entirely") is None
    assert accounts.peek_token(token) is None
    assert accounts.authenticate("ada@school.edu.ng", "correct horse battery") is not None


def test_a_link_cannot_be_claimed_twice_even_if_both_requests_passed_the_first_check(db):
    # Two browser requests can both see the link as valid, then race to use it.
    # Only one may win: the database update itself must refuse the second.
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    assert accounts.peek_token(token) and accounts.peek_token(token)
    assert accounts._consume_token(token) == {"email": "ada@school.edu.ng", "purpose": "signup"}
    assert accounts._consume_token(token) is None


def test_expired_link_is_rejected(db, monkeypatch):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    real = accounts.time.time
    monkeypatch.setattr(accounts.time, "time", lambda: real() + accounts.LINK_TTL_SECONDS + 5)
    assert accounts.peek_token(token) is None
    assert accounts.finish_with_password(token, "correct horse battery") is None
    assert accounts.get_account_by_email("ada@school.edu.ng") is None


def test_links_last_a_day_but_not_longer(db, monkeypatch):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    real = accounts.time.time
    monkeypatch.setattr(accounts.time, "time", lambda: real() + accounts.LINK_TTL_SECONDS - 60)
    assert accounts.peek_token(token) is not None
    monkeypatch.setattr(accounts.time, "time", lambda: real() + accounts.LINK_TTL_SECONDS + 60)
    assert accounts.peek_token(token) is None


def test_new_link_replaces_the_old_one(db):
    first = accounts.issue_token("ada@school.edu.ng", "signup")
    second = accounts.issue_token("ada@school.edu.ng", "signup")
    assert accounts.peek_token(first) is None and accounts.peek_token(second) is not None


def test_bad_tokens_and_purposes(db):
    for junk in [None, "", "short", "a" * 200, "has space in it and is long enough", "../../etc/passwd" * 3]:
        assert accounts.peek_token(junk) is None
        assert accounts.finish_with_password(junk or "", "correct horse battery") is None
    with pytest.raises(ValueError):
        accounts.issue_token("ada@school.edu.ng", "admin")


def test_tokens_are_not_stored_in_plain_text(db):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    raw = sqlite3.connect(config.ACCOUNTS_DB).execute("SELECT * FROM login_tokens").fetchall()
    assert token not in str(raw)


def test_weak_password_keeps_the_link_usable(db):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    with pytest.raises(ValueError, match="at least"):
        accounts.finish_with_password(token, "short")
    assert accounts.peek_token(token) is not None
    assert accounts.finish_with_password(token, "correct horse battery") is not None


def test_passwords_are_not_stored_in_plain_text(db):
    make_account(password="correct horse battery")
    raw = sqlite3.connect(config.ACCOUNTS_DB).execute("SELECT * FROM accounts").fetchall()
    assert "correct horse battery" not in str(raw)


# --------------------------------------------------------------------- password reset
def test_reset_changes_password_and_signs_everyone_out(db):
    account = make_account()
    cookie = accounts.issue_session(account)
    assert accounts.account_from_cookie(cookie) is not None
    token = accounts.issue_token(account.email, "reset")
    again = accounts.finish_with_password(token, "a brand new passphrase")
    assert again.id == account.id
    assert accounts.authenticate(account.email, "correct horse battery") is None
    assert accounts.authenticate(account.email, "a brand new passphrase") is not None
    assert accounts.account_from_cookie(cookie) is None                  # old sessions no longer work


def test_reset_does_not_reenable_a_disabled_account(db):
    account = make_account()
    accounts.set_disabled(account.id, True)
    token = accounts.issue_token(account.email, "reset")
    again = accounts.finish_with_password(token, "a brand new passphrase")
    assert again.disabled
    assert accounts.authenticate(account.email, "a brand new passphrase") is None


# ------------------------------------------------------------------------ sessions
def test_session_cookie_roundtrip_and_tampering(db):
    account = make_account()
    cookie = accounts.issue_session(account)
    assert accounts.account_from_cookie(cookie).email == account.email
    account_id, expiry, version, signature = cookie.split(".")
    for forged in [f"{int(account_id) + 1}.{expiry}.{version}.{signature}",
                   f"{account_id}.{int(expiry) + 999}.{version}.{signature}",
                   f"{account_id}.{expiry}.{version}.{'0' * len(signature)}",
                   f"{account_id}.{expiry}.{version}", "", "junk", "a.b.c.d", "x" * 500, None]:
        assert accounts.account_from_cookie(forged) is None, forged


def test_session_expires(db, monkeypatch):
    cookie = accounts.issue_session(make_account())
    real = accounts.time.time
    monkeypatch.setattr(accounts.time, "time", lambda: real() + accounts.SESSION_SECONDS + 5)
    assert accounts.account_from_cookie(cookie) is None


def test_disabling_or_deleting_kills_the_session(db):
    account = make_account()
    cookie = accounts.issue_session(account)
    accounts.set_disabled(account.id, True)
    assert accounts.account_from_cookie(cookie) is None
    assert accounts.authenticate(account.email, "correct horse battery") is None
    accounts.set_disabled(account.id, False)
    assert accounts.authenticate(account.email, "correct horse battery") is not None
    assert accounts.account_from_cookie(cookie) is None                  # the old cookie stays dead
    fresh = accounts.issue_session(accounts.get_account(account.id))
    assert accounts.delete_account(account.id) is True
    assert accounts.account_from_cookie(fresh) is None
    assert accounts.delete_account(account.id) is False
    assert accounts.set_disabled(999, True) is False


def test_session_secret_is_stable_and_stored(db):
    account = make_account()
    cookie = accounts.issue_session(account)
    accounts._secret_cache.clear()                                      # as after a server restart
    assert accounts.account_from_cookie(cookie) is not None


def test_last_sign_in_is_recorded(db):
    account = make_account()
    assert account.last_login_at is None
    assert accounts.authenticate(account.email, "correct horse battery").last_login_at


def test_list_accounts_sorted(db):
    make_account("zed@school.edu.ng")
    make_account("ada@school.edu.ng")
    assert [a.email for a in accounts.list_accounts()] == ["ada@school.edu.ng", "zed@school.edu.ng"]


# ------------------------------------------------------------------------ cohort code
def test_cohort_code_lifecycle(db):
    assert accounts.get_signup_code() is None
    assert not accounts.signup_code_matches("anything")
    assert not accounts.signup_code_matches(None)
    code = accounts.new_signup_code()
    assert len(code.replace("-", "")) == accounts.CODE_LENGTH and code.count("-") == 2
    assert accounts.get_signup_code() == code
    raw = code.replace("-", "")
    for variant in (code, raw, code.lower(), " " + code.lower().replace("-", " ") + " "):
        assert accounts.signup_code_matches(variant), variant
    assert not accounts.signup_code_matches(raw[:-1]) and not accounts.signup_code_matches("")
    newer = accounts.new_signup_code()
    assert newer != code and not accounts.signup_code_matches(code) and accounts.signup_code_matches(newer)
    accounts.clear_signup_code()
    assert accounts.get_signup_code() is None and not accounts.signup_code_matches(newer)


def test_cohort_code_uses_only_readable_characters(db):
    for _ in range(30):
        assert set(accounts.new_signup_code().replace("-", "")) <= set(accounts.CODE_ALPHABET)
    assert not set("0O1I") & set(accounts.CODE_ALPHABET)


def test_cohort_code_is_not_the_session_key(db):
    accounts.new_signup_code()
    assert accounts.get_signup_code().replace("-", "").encode() != accounts._secret()


def test_create_account_directly(db):
    account = accounts.create_account("Ada@School.edu.ng".lower(), "correct horse battery")
    assert account.email == "ada@school.edu.ng" and not account.disabled
    assert accounts.authenticate("ada@school.edu.ng", "correct horse battery")
    with pytest.raises(ValueError):
        accounts.create_account("ada@school.edu.ng", "another long password")      # already exists
    with pytest.raises(ValueError):
        accounts.create_account("bob@school.edu.ng", "short")                        # weak
    assert accounts.get_account_by_email("bob@school.edu.ng") is None
    assert accounts.authenticate("ada@school.edu.ng", "correct horse battery")      # first account untouched


def test_signup_link_cannot_overwrite_an_existing_account(db):
    token = accounts.issue_token("ada@school.edu.ng", "signup")
    accounts.create_account("ada@school.edu.ng", "correct horse battery")           # signed up with the code meanwhile
    assert accounts.finish_with_password(token, "attacker chosen password") is None
    assert accounts.authenticate("ada@school.edu.ng", "correct horse battery")
    assert not accounts.authenticate("ada@school.edu.ng", "attacker chosen password")


def test_reset_link_cannot_create_an_account(db):
    token = accounts.issue_token("ghost@school.edu.ng", "reset")
    assert accounts.finish_with_password(token, "correct horse battery") is None
    assert accounts.get_account_by_email("ghost@school.edu.ng") is None


def test_rate_limiter_allowed_does_not_count(monkeypatch):
    limiter = accounts.RateLimiter(limit=2, window=60)
    for _ in range(10):
        assert limiter.allowed("a")
    limiter.hit("a"); limiter.hit("a")
    assert not limiter.allowed("a") and limiter.allowed("b")


# ------------------------------------------------------------------- abuse protection
def test_rate_limiter_blocks_then_recovers(monkeypatch):
    limiter = accounts.RateLimiter(limit=3, window=60)
    clock = [1000.0]
    monkeypatch.setattr(accounts.time, "monotonic", lambda: clock[0])
    assert [limiter.hit("a") for _ in range(4)] == [True, True, True, False]
    assert limiter.hit("b") is True                                     # other keys are independent
    clock[0] += 61
    assert limiter.hit("a") is True
    limiter.reset("a")
    assert [limiter.hit("a") for _ in range(3)] == [True, True, True]


def test_rate_limiter_memory_is_bounded(monkeypatch):
    limiter = accounts.RateLimiter(limit=1, window=60, max_keys=3)
    assert all(limiter.hit(k) for k in ["a", "b", "c"])
    assert limiter.hit("d") is False                                    # full of recent keys: refuse new ones
    assert limiter.hit("a") is False                                    # known keys still counted


def test_safe_next_only_allows_local_paths():
    assert accounts.safe_next("/courses/3?x=1") == "/courses/3?x=1"
    assert accounts.safe_next(None) == "/" and accounts.safe_next("") == "/"
    for bad in ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)",
                "/ok\r\nSet-Cookie: a=b", "/" + "a" * 600, "evil.example"]:
        assert accounts.safe_next(bad) == "/", bad


# ------------------------------------------------------------------------- terminal tool
def test_manage_users_tool(db, capsys, monkeypatch):
    import manage_users
    monkeypatch.setattr(config, "PUBLIC_URL", "https://study.test")
    assert manage_users.main(["list"]) == 0
    assert "No student accounts" in capsys.readouterr().out
    assert manage_users.main(["code"]) == 0
    code = capsys.readouterr().out.strip()
    assert accounts.signup_code_matches(code)
    assert manage_users.main(["code"]) == 0 and capsys.readouterr().out.strip() == code    # stable until replaced
    assert manage_users.main(["newcode"]) == 0
    assert capsys.readouterr().out.strip() != code and not accounts.signup_code_matches(code)
    assert manage_users.main(["closecode"]) == 0 and accounts.get_signup_code() is None
    capsys.readouterr()

    assert manage_users.main(["invite", "friend@gmail.com"]) == 0
    out = capsys.readouterr().out
    token = out.split("token=")[1].split()[0]
    assert "https://study.test/verify?token=" in out
    account = accounts.finish_with_password(token, "correct horse battery")
    assert account.email == "friend@gmail.com"                          # links work for any domain
    assert manage_users.main(["invite", "friend@gmail.com"]) == 1        # already has an account
    capsys.readouterr()
    assert manage_users.main(["reset", "friend@gmail.com"]) == 0
    reset = capsys.readouterr().out.split("token=")[1].split()[0]
    assert accounts.finish_with_password(reset, "a brand new passphrase")
    assert manage_users.main(["reset", "nobody@gmail.com"]) == 1
    assert manage_users.main(["disable", "friend@gmail.com"]) == 0
    assert accounts.get_account_by_email("friend@gmail.com").disabled
    assert manage_users.main(["enable", "friend@gmail.com"]) == 0
    assert manage_users.main(["delete", "friend@gmail.com"]) == 0
    assert manage_users.main(["delete", "friend@gmail.com"]) == 1
    assert manage_users.main(["invite", "not-an-email"]) == 1
    assert manage_users.main(["list", "extra"]) == 1
    assert manage_users.main([]) == 1
