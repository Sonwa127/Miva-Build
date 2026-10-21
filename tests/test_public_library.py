"""Access-control, video publishing, and faithful PDF delivery regression tests."""
import struct

import fitz
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.auth import COOKIE_NAME, configure_admin
from api.deps import get_store
from api.routes import admin
from archive import analytics, config, courses, course_weeks, registry, resources, summaries, glossary


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_DB", tmp_path / "app.sqlite")
    monkeypatch.setattr(config, "REGISTRY_DB", tmp_path / "registry.sqlite")
    monkeypatch.setattr(courses, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(analytics, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(summaries, "DB_PATH", config.APP_DB)
    monkeypatch.setattr(glossary, "DB_PATH", config.APP_DB)
    admin._attempts.clear()
    # No vector database or cloud service is needed to exercise HTTP delivery.
    class Store:
        def get_page(self, doc_id, page):
            return ["Original document text"]

        def delete_doc(self, doc_id):
            pass

        def count_doc(self, doc_id):
            return 0

    app.dependency_overrides[get_store] = lambda: Store()
    client = TestClient(app)
    course = courses.create_course("PHY 101", "Mechanics", description="Motion and forces")
    yield client, course, tmp_path
    client.close()
    app.dependency_overrides.clear()
    admin._attempts.clear()


def sign_in(client):
    configure_admin("a-long-test-password-2026")
    response = client.post("/api/admin/login", json={"password": "a-long-test-password-2026"})
    assert response.status_code == 200
    return response


def test_students_browse_free_pages_and_cannot_manage_content(library):
    client, course, _ = library
    for path in ["/", "/courses", f"/courses/{course.id}", "/resources", "/study", "/admin/login"]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert "Alex Morgan" not in response.text
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert "generateDeckForm" not in client.get("/study").text.split("{%", 1)[0].split("<script>", 1)[0]
    for method, path in [
        ("POST", "/api/courses"), ("PUT", f"/api/courses/{course.id}"),
        ("DELETE", f"/api/courses/{course.id}"), ("POST", "/api/documents/upload"),
        ("DELETE", "/api/documents/test"), ("POST", "/api/resources"),
        ("PUT", "/api/resources/test"), ("DELETE", "/api/resources/test"),
        ("POST", "/api/study/flashcards/generate"), ("POST", "/api/study/summaries/generate"),
        ("POST", "/api/study/glossary/generate"), ("POST", "/api/study/quizzes/generate"),
        ("POST", "/api/study/flashcards/review"),
    ]:
        assert client.request(method, path).status_code == 401, path
    for path in ["/api/qa/history", "/api/evaluation/history", "/api/analytics/activity"]:
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12s",
    "https://youtu.be/dQw4w9WgXcQ?si=test",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
])
def test_youtube_link_formats(url):
    canonical, video_id = resources.normalize_url(url, "youtube")
    assert video_id == "dQw4w9WgXcQ"
    assert canonical == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("url,kind", [
    ("https://youtube.com.evil.example/watch?v=dQw4w9WgXc", "youtube"),
    ("javascript:alert(1)", "link"), ("file:///etc/passwd", "link"),
    ("https://youtube.com/playlist?list=abc", "youtube"),
    ("https://www.youtube.com/watch?v=bad<script>", "youtube"),
    ("https://user:password@example.org", "link"),
])
def test_unsafe_and_nonvideo_links_rejected(url, kind):
    with pytest.raises(ValueError):
        resources.normalize_url(url, kind)


def test_admin_publishes_edits_and_removes_video(library):
    client, course, _ = library
    login = sign_in(client)
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert client.get("/admin").status_code == 200
    assert client.get("/admin").headers["cache-control"] == "no-store"
    payload = {"title": "A useful lesson", "url": "https://youtu.be/dQw4w9WgXcQ", "kind": "youtube", "course": course.code, "description": "Watch before revising."}
    response = client.post("/api/resources", json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    client.cookies.clear()
    watch = client.get(f"/watch/{item['id']}")
    assert watch.status_code == 200
    assert "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?" in watch.text
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in watch.text
    assert "Watch before revising." in client.get(f"/courses/{course.id}").text
    assert len(client.get("/api/resources", params={"course": course.code}).json()) == 1
    assert "A useful lesson" in client.get("/resources", params={"q": "useful", "kind": "youtube"}).text
    assert "A useful lesson" not in client.get("/resources", params={"kind": "pdf"}).text
    sign_in(client)
    payload["title"] = "Updated lesson"
    assert client.put(f"/api/resources/{item['id']}", json=payload).status_code == 200
    assert client.delete(f"/api/courses/{course.id}").status_code == 409
    assert client.delete(f"/api/resources/{item['id']}").status_code == 204
    assert client.get(f"/watch/{item['id']}").status_code == 404


def test_sessions_password_reset_logout_and_cross_site_protection(library):
    client, course, _ = library
    sign_in(client)
    assert client.post("/api/resources", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    token = client.cookies.get(COOKIE_NAME)
    client.cookies.set(COOKIE_NAME, token[:-1] + ("a" if token[-1] != "a" else "b"))
    assert not client.get("/api/admin/session").json()["authenticated"]
    client.cookies.clear()
    sign_in(client)
    assert client.post("/api/admin/logout").status_code == 200
    assert not client.get("/api/admin/session").json()["authenticated"]
    sign_in(client)
    configure_admin("a-new-password-that-invalidates-old-sessions")
    assert not client.get("/api/admin/session").json()["authenticated"]


def test_login_has_no_default_password_and_limits_attempts(library):
    client, _, _ = library
    assert client.post("/api/admin/login", json={"password": "admin"}).status_code == 503
    configure_admin("a-long-test-password-2026")
    for _ in range(5):
        assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 429


def test_first_run_browser_setup_is_local_only_and_cannot_overwrite_password(library):
    client, _, _ = library
    payload = {"password": "first-browser-password-2026", "confirmation": "first-browser-password-2026"}
    assert client.post("/api/admin/setup", json=payload).status_code == 403
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 55000)) as local:
        page = local.get("/admin/login")
        assert 'id="setupForm"' in page.text
        assert 'id="showPasswords"' in page.text
        assert local.post("/api/admin/setup", json=payload, headers={"Origin": "https://evil.example"}).status_code == 403
        assert local.post("/api/admin/setup", json={**payload, "confirmation": "different-password-2026"}).status_code == 422
        assert local.post("/api/admin/setup", json={"password": "short", "confirmation": "short"}).status_code == 422
        response = local.post("/api/admin/setup", json=payload, headers={"Origin":"http://localhost"})
        assert response.status_code == 201, response.text
        assert local.get("/api/admin/session").json()["authenticated"]
        assert local.get("/admin").status_code == 200
        assert local.post("/api/admin/setup", json=payload).status_code == 409
        local.post("/api/admin/logout")
        assert 'id="setupForm"' not in local.get("/admin/login").text
        assert 'id="loginForm"' in local.get("/admin/login").text


def test_localhost_hostname_does_not_allow_remote_setup(library):
    _, _, _ = library
    with TestClient(app, base_url="http://localhost", client=("203.0.113.10", 55000)) as remote:
        payload = {"password":"a-remote-admin-password", "confirmation":"a-remote-admin-password"}
        assert remote.post("/api/admin/setup", json=payload).status_code == 403


def add_original_pdf(tmp_path, course):
    path = tmp_path / "Lecture layout.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=900, height=500)
        page.insert_text((40, 60), "Left column", fontsize=24)
        page.insert_text((480, 60), "Right column", fontsize=24)
        page.draw_rect(fitz.Rect(40, 100, 400, 350), color=(0, 0, 1), fill=(0.9, 0.9, 1))
        pdf.new_page(width=500, height=900)
        pdf.save(path)
    registry.add(registry.DocRecord("layout-test", "a" * 64, "Formatted lecture", course.code,
                                   path.name, str(path), 2, 0, registry.now_iso()))
    return path


def test_pdf_preserves_original_bytes_layout_and_page_bounds(library):
    client, course, tmp_path = library
    path = add_original_pdf(tmp_path, course)
    original = client.get("/api/documents/layout-test/file")
    assert original.status_code == 200
    assert original.content == path.read_bytes()
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["content-disposition"].startswith("inline")
    download = client.get("/api/documents/layout-test/file?download=true")
    assert download.headers["content-disposition"].startswith("attachment")
    image = client.get("/api/documents/layout-test/pages/1/image")
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", image.content[16:24])
    assert width / height == pytest.approx(900 / 500, abs=0.01)
    second = client.get("/api/documents/layout-test/pages/2/image")
    width2, height2 = struct.unpack(">II", second.content[16:24])
    assert height2 > width2
    for page in [0, 3]:
        assert client.get(f"/api/documents/layout-test/pages/{page}/image").status_code == 404
    assert client.get("/api/documents/missing/file").status_code == 404
    viewer = client.get("/viewer/layout-test?page=2")
    assert viewer.status_code == 200
    assert '/pages/2/image' in viewer.text
    assert 'Original PDF view' in viewer.text


def test_scanned_pdf_upload_can_be_read_without_text_index(library):
    client, course, tmp_path = library
    sign_in(client)
    with fitz.open() as pdf:
        pdf.new_page(width=400, height=600).draw_rect(fitz.Rect(20, 20, 350, 550), fill=(0.4, 0.8, 0.7))
        content = pdf.tobytes()
    response = client.post("/api/documents/upload", data={"course": course.code}, files={"file": ("scan.pdf", content, "application/pdf")})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["chunk_count"] == 0
    client.cookies.clear()
    assert client.get(f"/api/documents/{item['doc_id']}/file").content == content
    assert client.get(f"/api/documents/{item['doc_id']}/pages/1/image").status_code == 200


def test_resource_titles_are_escaped_and_links_validated(library):
    client, course, _ = library
    sign_in(client)
    payload = {"title": '<script>alert("test")</script>', "description": "<img src=x onerror=alert(1)>", "kind": "link", "url": "https://example.org/reading", "course": course.code}
    response = client.post("/api/resources", json=payload)
    assert response.status_code == 201
    page = client.get("/resources").text
    assert '<script>alert("test")</script>' not in page
    assert '&lt;script&gt;' in page
    payload["url"] = "javascript:alert(1)"
    assert client.post("/api/resources", json=payload).status_code == 422
    payload["url"] = "https://example.org"
    payload["course"] = "missing-course"
    assert client.post("/api/resources", json=payload).status_code == 422


@pytest.mark.parametrize("url,expected_kind,expected_player", [
    ("https://youtube.com/playlist?list=PL1234567890abcdefghij", "youtube_playlist", "https://www.youtube-nocookie.com/embed/videoseries"),
    ("https://vimeo.com/76979871/abc123def0", "vimeo", "https://player.vimeo.com/video/76979871?h=abc123def0"),
    ("https://vimeo.com/showcase/5376202", "vimeo_showcase", "https://vimeo.com/album/5376202/embed"),
    ("https://www.loom.com/share/e5b8c04bca094dd8a5507925ab887002", "loom", "https://www.loom.com/embed/e5b8c04bca094dd8a5507925ab887002"),
    ("https://geo.dailymotion.com/player/x8lr5.html?playlist=x5zhzj", "dailymotion_playlist", "https://geo.dailymotion.com/player/x8lr5.html?playlist=x5zhzj"),
    ("https://cdn.example.org/lecture.mp4?signature=abc123", "video_file", "https://cdn.example.org/lecture.mp4?signature=abc123"),
])
def test_admin_publishes_and_edits_multiple_video_providers(library, url, expected_kind, expected_player):
    client, course, _ = library
    sign_in(client)
    payload = {"title": "Course video collection", "kind": "video", "url": url, "course":course.code}
    response = client.post("/api/resources", json=payload)
    assert response.status_code == 201, response.text
    resource = response.json()
    assert resource["kind"] == expected_kind
    assert resource["is_video"]
    assert expected_player in resource["embed_url"]
    assert client.get("/admin").status_code == 200
    payload["title"] = "Updated collection"
    updated = client.put(f"/api/resources/{resource['id']}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["embed_url"] == resource["embed_url"]
    client.cookies.clear()
    watch = client.get(f"/watch/{resource['id']}")
    assert watch.status_code == 200
    assert expected_player in watch.text
    assert ('<video ' in watch.text) is (expected_kind == "video_file")
    assert "Updated collection" in client.get("/resources?kind=video").text
    assert ("Updated collection" in client.get("/resources?kind=playlist").text) is resource["is_playlist"]
    assert "Updated collection" in client.get(f"/courses/{course.id}").text


def test_course_weeks_are_admin_managed_and_numerically_ordered(library):
    client, course, _ = library
    path = f"/api/courses/{course.id}/weeks"
    assert client.post(path, json={"number":1}).status_code == 401
    assert client.delete(path + "/1").status_code == 401
    sign_in(client)
    for number in [10, 2, 1]:
        response = client.post(path, json={"number":number, "title":f"Topic {number}", "description":"Learning goals"})
        assert response.status_code == 200, response.text
    assert [week["number"] for week in client.get(path).json()] == [1, 2, 10]
    assert client.post(path, json={"number":2, "title":"Updated topic"}).status_code == 200
    assert len(client.get(path).json()) == 3
    assert client.get(path).json()[1]["title"] == "Updated topic"
    for invalid in [0, -1, 53, 1.5, True, "2"]:
        assert client.post(path, json={"number":invalid}).status_code == 422
    assert client.post("/api/courses/missing/weeks", json={"number":1}).status_code == 404
    assert client.delete(path + "/10").status_code == 204
    assert client.delete(path + "/10").status_code == 404
    client.cookies.clear()
    page = client.get(f"/courses/{course.id}")
    assert page.status_code == 200
    assert page.text.index('id="week-1"') < page.text.index('id="week-2"')
    assert "Updated topic" in page.text


def test_general_and_weekly_materials_are_separate_and_can_be_moved(library):
    client, course, tmp_path = library
    pdf_path = add_original_pdf(tmp_path, course)
    sign_in(client)
    week_path = f"/api/courses/{course.id}/weeks"
    client.post(week_path, json={"number":1,"title":"Getting started"})
    payload = {"title":"Weekly worked examples", "kind":"link", "url":"https://example.org/examples", "course":course.code,"week":1}
    weekly = client.post("/api/resources", json=payload)
    assert weekly.status_code == 201, weekly.text
    resource_id = weekly.json()["id"]
    general = client.post("/api/resources", json={**payload,"title":"Full course reference","week":0}).json()
    page = client.get(f"/courses/{course.id}").text
    general_section = page.split('id="general-materials"',1)[1].split('</section>',1)[0]
    week_section = page.split('id="week-1"',1)[1].split('</details>',1)[0]
    assert "Formatted lecture" in general_section and "Full course reference" in general_section
    assert "Weekly worked examples" not in general_section
    assert "Weekly worked examples" in week_section and "Formatted lecture" not in week_section
    assert len(client.get("/api/resources",params={"course":course.code,"week":1}).json()) == 1
    assert client.get("/api/resources",params={"course":course.code,"week":0}).json()[0]["id"] == general["id"]
    assert client.patch("/api/documents/layout-test/placement",json={"week":1}).status_code == 200
    assert registry.get("layout-test").week == 1
    assert client.get("/api/documents/layout-test/file").content == pdf_path.read_bytes()
    assert client.get("/api/documents",params={"course":course.code,"week":0}).json() == []
    assert client.get("/api/documents",params={"course":course.code,"week":1}).json()[0]["week"] == 1
    assert client.delete(week_path + "/1").status_code == 409
    # Legacy clients editing details without a week field preserve the placement.
    payload.pop("week")
    assert client.put(f"/api/resources/{resource_id}",json=payload).json()["week"] == 1
    assert client.put(f"/api/resources/{resource_id}",json={**payload,"week":0}).json()["week"] == 0
    assert client.patch("/api/documents/layout-test/placement",json={"week":0}).json()["week"] == 0
    assert client.delete(week_path + "/1").status_code == 204
    client.cookies.clear()
    assert client.patch("/api/documents/layout-test/placement",json={"week":1}).status_code == 401


def test_week_placement_must_belong_to_selected_course(library):
    client, course, tmp_path = library
    add_original_pdf(tmp_path, course)
    other = courses.create_course("STA 111","Descriptive Statistics")
    course_weeks.save_week(course.code,1,"Motion")
    sign_in(client)
    payload = {"title":"Extra reading", "kind":"link", "url":"https://example.org/reading", "course":other.code,"week":1}
    assert client.post("/api/resources",json=payload).status_code == 422
    payload["course"] = ""
    assert client.post("/api/resources",json=payload).status_code == 422
    for week in [-1,53,True,1.5]:
        assert client.patch("/api/documents/layout-test/placement",json={"week":week}).status_code == 422
    assert client.patch("/api/documents/layout-test/placement",json={"week":2}).status_code == 422
    assert client.patch("/api/documents/missing/placement",json={"week":0}).status_code == 404
    assert client.get("/api/documents?week=-1").status_code == 422
    assert client.get("/api/resources?week=53").status_code == 422


def test_pdf_upload_keeps_week_on_reupload_and_rejects_accidental_moves(library):
    client, course, _ = library
    sign_in(client)
    course_weeks.save_week(course.code,1)
    course_weeks.save_week(course.code,2)
    with fitz.open() as pdf:
        pdf.new_page().draw_rect(fitz.Rect(20,20,100,100),fill=(0.2,0.4,0.7))
        content = pdf.tobytes()
    def upload(week=None):
        data = {"course":course.code}
        if week is not None:
            data["week"] = str(week)
        return client.post("/api/documents/upload",data=data,files={"file":("weekly.pdf",content,"application/pdf")})
    first = upload(1)
    assert first.status_code == 201, first.text
    assert first.json()["week"] == 1
    repeated = upload()
    assert repeated.status_code == 201 and repeated.json()["week"] == 1
    assert upload(2).status_code == 409
    assert registry.get(first.json()["doc_id"]).week == 1
    assert upload(3).status_code == 422


def test_week_titles_are_escaped_and_course_deletion_respects_outline(library):
    client, course, _ = library
    sign_in(client)
    payload = {"number":1,"title":"<script>alert('week')</script>","description":"<img src=x onerror=alert(1)>"}
    client.post(f"/api/courses/{course.id}/weeks",json=payload)
    page = client.get(f"/courses/{course.id}").text
    assert "<script>alert('week')</script>" not in page
    assert "&lt;script&gt;" in page and "&lt;img" in page
    assert client.delete(f"/api/courses/{course.id}").status_code == 409
    assert client.get("/admin").status_code == 200
