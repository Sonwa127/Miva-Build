"""Public Ask AI presentation must be understandable and honest about demo mode."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import app
from archive import config, courses


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(courses, "list_courses", lambda: [
        SimpleNamespace(code="PHY 101", name="Mechanics & Motion"),
        SimpleNamespace(code="STA 111", name="Descriptive Statistics"),
    ])
    with TestClient(app) as browser:
        yield browser


@pytest.mark.parametrize("provider,demo", [("offline", True), ("mistral", False)])
def test_ask_explains_sources_and_provider_state(client, monkeypatch, provider, demo):
    monkeypatch.setattr(config, "LLM_PROVIDER", provider)
    response = client.get("/ask?course_id=PHY%20101")
    assert response.status_code == 200
    html = response.text
    assert 'value="PHY 101" selected' in html
    assert "Mechanics &amp; Motion" in html
    assert "From your reading" in html
    assert "Short follow-ups like" in html
    assert ("Demo mode" in html) is demo
    assert "Confidence:" not in html
    assert "100% Vector Fidelity" not in html
    assert "zero hallucinated" not in html
    assert "Red-Black" not in html
    assert "Add Card to Deck" not in html
    assert 'aria-describedby="questionHint"' in html
    assert '/static/css/ask.css' in html
    assert '/static/js/ask.js' in html


@pytest.mark.parametrize("path", ["/static/css/ask.css", "/static/js/ask.js"])
def test_ask_assets_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert len(response.content) > 100
