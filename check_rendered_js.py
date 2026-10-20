"""Render every live page and syntax-check its inline JavaScript with Node."""
from __future__ import annotations

import subprocess
from html.parser import HTMLParser
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import app


class InlineScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and not dict(attrs).get("src"):
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture:
            self.scripts.append("".join(self._parts))
            self._capture = False


def main() -> int:
    client = TestClient(app)
    courses = client.get("/api/courses").json()
    documents = client.get("/api/documents").json()
    pages = ["/", "/courses", "/resources", "/ask", "/study", "/admin/login", "/admin"]
    pages.extend(f"/courses/{course['id']}" for course in courses)
    pages.extend(f"/viewer/{document['doc_id']}?page=1" for document in documents)

    failures = 0
    for path in pages:
        # This is a local render-only diagnostic. It never logs into a live server
        # or changes the administrator account.
        if path == "/admin":
            with patch("api.app.is_admin", return_value=True):
                response = client.get(path)
        else:
            response = client.get(path)
        if response.status_code != 200:
            failures += 1
            print(f"FAIL {path}: HTTP {response.status_code}")
            continue

        collector = InlineScriptCollector()
        collector.feed(response.text)
        errors: list[str] = []
        for number, script in enumerate(collector.scripts, start=1):
            result = subprocess.run(
                ["node", "--check", "-"],
                input=script,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            if result.returncode:
                errors.append(f"script {number}: {result.stderr.strip()}")

        if errors:
            failures += len(errors)
            print(f"FAIL {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"OK   {path} ({len(collector.scripts)} inline scripts)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
