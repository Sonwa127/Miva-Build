"""Private authoring is public to use but local-only; shared authoring stays admin-only."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
from archive import courses


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(courses, "list_courses", lambda: [SimpleNamespace(code="PHY 101", name="Mechanics & Motion")])
    monkeypatch.setattr("api.app.is_admin", lambda request: False)
    with TestClient(app) as client:
        yield client


def test_public_students_can_create_private_cards_without_admin_access(client):
    response = client.get("/study?course_id=PHY%20101")
    assert response.status_code == 200
    html = response.text
    assert "My private flashcards" in html
    assert "Saved only in this browser" in html
    assert "Anyone using this browser profile can access them" in html
    assert "Clearing browser data removes them" in html
    assert "Export backup" in html and "Import backup" in html
    assert "Mechanics &amp; Motion" in html
    assert '<option value="PHY 101" selected>' in html
    assert 'id="privateCardQuestion"' in html
    assert 'id="privateCardAnswer"' in html
    assert 'id="privateReviewDialog"' in html
    assert "Shared class decks" in html
    assert "+ Generate New Set" not in html
    assert 'id="generateDeckForm"' not in html


@pytest.mark.parametrize("path", ["/static/css/private-flashcards.css", "/static/js/private-flashcards.js", "/static/js/private-flashcards-store.js"])
def test_private_assets_are_available(client, path):
    assert client.get(path).status_code == 200
