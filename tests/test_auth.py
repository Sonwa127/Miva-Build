import sqlite3

import pytest

from archive import auth, config


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "USERS_DB", tmp_path / "data" / "users.sqlite")
    return tmp_path


def test_add_user_returns_a_token_that_authenticates(db):
    token = auth.add_user("Ada", "contributor")
    assert token.startswith("ca_") and len(token) > 30
    user = auth.authenticate(token)
    assert user.name == "ada" and user.role == "contributor"      # names are stored lowercase


def test_token_is_not_stored_in_plain_text(db):
    token = auth.add_user("ada")
    raw = sqlite3.connect(config.USERS_DB).execute("SELECT * FROM users").fetchall()
    assert token not in str(raw)


def test_wrong_empty_and_malformed_tokens_fail(db):
    auth.add_user("ada")
    assert auth.authenticate("ca_not-a-real-token") is None
    assert auth.authenticate("") is None and auth.authenticate(None) is None
    assert auth.authenticate("no-prefix") is None


def test_duplicate_name_and_bad_input_are_rejected(db):
    auth.add_user("ada")
    with pytest.raises(ValueError, match="already exists"):
        auth.add_user("ADA")
    with pytest.raises(ValueError, match="Unknown role"):
        auth.add_user("bob", "superuser")
    with pytest.raises(ValueError, match="Names must be"):
        auth.add_user("has space")
    with pytest.raises(ValueError, match="Names must be"):
        auth.add_user("")


def test_list_and_remove(db):
    auth.add_user("zed", "admin")
    t = auth.add_user("ada")
    assert [(u.name, u.role) for u in auth.list_users()] == [("ada", "reader"), ("zed", "admin")]
    assert auth.remove_user("Ada") is True
    assert auth.remove_user("ada") is False
    assert auth.authenticate(t) is None                           # a removed user's token dies


def test_reset_token_invalidates_the_old_one(db):
    old = auth.add_user("ada")
    new = auth.reset_token("ada")
    assert new and new != old
    assert auth.authenticate(old) is None
    assert auth.authenticate(new).name == "ada"
    assert auth.reset_token("nobody") is None


def test_role_hierarchy(db):
    reader = auth.User("r", "reader")
    contrib = auth.User("c", "contributor")
    admin = auth.User("a", "admin")
    assert auth.has_role(reader, "reader") and not auth.has_role(reader, "contributor")
    assert auth.has_role(contrib, "reader") and auth.has_role(contrib, "contributor")
    assert not auth.has_role(contrib, "admin")
    assert all(auth.has_role(admin, r) for r in auth.ROLES)
    assert not auth.has_role(None, "reader") and not auth.has_role(admin, "nonsense")


def test_cli_user_commands(db, capsys):
    import cli
    assert cli.main(["users"]) == 0
    assert "No users yet" in capsys.readouterr().out
    assert cli.main(["adduser", "ada", "--role", "admin"]) == 0
    out = capsys.readouterr().out
    assert "Created admin 'ada'" in out and "ca_" in out
    assert cli.main(["adduser", "ada"]) == 1                      # duplicate -> clean error, exit 1
    assert "already exists" in capsys.readouterr().out
    assert cli.main(["users"]) == 0 and "ada" in capsys.readouterr().out
    assert cli.main(["deluser", "ada"]) == 0
    assert cli.main(["deluser", "ada"]) == 1
