"""Record library changes made by admins in the activity log (who, what, when).

Only successful changes made through the admin tools are recorded. Reading pages,
students asking questions and failed or refused requests are not. Student account
actions, collaborator changes and sign-ins are logged by their own handlers with
more detail (for example the student's email).
"""
from __future__ import annotations

import re

from fastapi import Request

from .auth import audit

_ID = r"[^/]+"
LABELS: list[tuple[str, re.Pattern, str]] = [
    (method, re.compile(pattern), text) for method, pattern, text in [
        ("POST", rf"^/api/documents/upload$", "Uploaded a PDF"),
        ("PATCH", rf"^/api/documents/{_ID}/placement$", "Changed where a PDF is placed"),
        ("DELETE", rf"^/api/documents/{_ID}$", "Removed a PDF"),
        ("POST", rf"^/api/resources$", "Added a video or link"),
        ("PUT", rf"^/api/resources/{_ID}$", "Edited a video or link"),
        ("DELETE", rf"^/api/resources/{_ID}$", "Deleted a video or link"),
        ("POST", rf"^/api/courses$", "Added a course"),
        ("PUT", rf"^/api/courses/{_ID}$", "Edited a course"),
        ("DELETE", rf"^/api/courses/{_ID}$", "Deleted a course"),
        ("POST", rf"^/api/courses/{_ID}/weeks$", "Saved a course week"),
        ("DELETE", rf"^/api/courses/{_ID}/weeks/{_ID}$", "Deleted a course week"),
        ("POST", rf"^/api/study/flashcards/generate$", "Generated flashcards"),
        ("POST", rf"^/api/study/quizzes/generate$", "Generated a quiz"),
        ("POST", rf"^/api/study/summaries/generate$", "Generated a summary"),
        ("POST", rf"^/api/study/glossary/generate$", "Generated a glossary"),
    ]
]


def describe(method: str, path: str) -> str | None:
    for label_method, pattern, text in LABELS:
        if method == label_method and pattern.match(path):
            return text
    return None


async def record_admin_activity(request: Request, call_next):
    response = await call_next(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
        text = describe(request.method, request.url.path)
        if text:
            audit(request, text, request.url.path)
    return response
