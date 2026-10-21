"""Shared test setup: tests never touch the real accounts, admin logins or activity log in data/."""
import pytest

from archive import config


@pytest.fixture(autouse=True)
def _isolated_accounts_database(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(config, "ACCOUNTS_DB", tmp_path_factory.mktemp("accounts") / "accounts.sqlite")
