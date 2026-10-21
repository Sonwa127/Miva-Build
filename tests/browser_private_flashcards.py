"""Manual, isolated Chrome checks: python tests/browser_private_flashcards.py.

No live data or credentials. Private writes must never send HTTP requests.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from fastapi.testclient import TestClient
from api.app import app
from browser_smoke import CHROME, _json_request, _wait_for_debugger
from websockets.sync.client import connect

with patch("archive.courses.list_courses", return_value=[SimpleNamespace(code="PHY 101", name="Physics"), SimpleNamespace(code="STA 111", name="Descriptive Statistics")]), patch("api.app.is_admin", return_value=False):
    with TestClient(app) as client:
        html = client.get("/study?course_id=PHY%20101").content
posts = []


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "frontend"), **kwargs)

    def do_GET(self):
        content = html if self.path.startswith("/study") else b"[]" if self.path.startswith("/api/") else None
        if content is None:
            super().do_GET()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if self.path.startswith("/study") else "application/json")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        posts.append(self.path)
        self.send_error(500, "Private content must not be posted")

    def log_message(self, *args):
        pass


scratch = ROOT / ".test-runs"
scratch.mkdir(exist_ok=True)
profile = Path(tempfile.mkdtemp(prefix="private-cards-browser-", dir=scratch))
server = ThreadingHTTPServer(("127.0.0.1", 8013), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
process = subprocess.Popen([str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=9226", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def check(width, height):
    target = _json_request("http://127.0.0.1:9226/json/new?about:blank", method="PUT")
    with connect(target["webSocketDebuggerUrl"], open_timeout=5) as socket:
        counter = 0

        def command(method, params=None):
            nonlocal counter
            counter += 1
            socket.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
            while True:
                event = json.loads(socket.recv(timeout=15))
                if event.get("method") == "Runtime.exceptionThrown":
                    raise AssertionError(event)
                if event.get("id") == counter:
                    assert "error" not in event, event
                    result = event.get("result", {})
                    assert "exceptionDetails" not in result, result
                    return result

        def evaluate(expression):
            return command("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})["result"].get("value")

        def assert_js(expression, reason):
            assert evaluate(expression), reason

        def capture(name):
            if "--no-screenshots" in sys.argv:
                return
            command("Page.bringToFront")
            time.sleep(.3)
            try:
                shot = command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            except AssertionError as err:
                if "Unable to capture screenshot" not in str(err):
                    raise
                shot = command("Page.captureScreenshot", {"format": "png", "fromSurface": False})
            (scratch / f"private-{name}-{width}.png").write_bytes(base64.b64decode(shot["data"]))

        command("Runtime.enable")
        command("Page.enable")
        command("Page.addScriptToEvaluateOnNewDocument", {"source": "window.confirm=()=>true;"})
        command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        command("Page.navigate", {"url": "http://127.0.0.1:8013/study"})
        time.sleep(2)
        evaluate("localStorage.removeItem(PrivateFlashcards.KEY); dispatchEvent(new StorageEvent('storage',{key:PrivateFlashcards.KEY}));")
        assert_js("document.documentElement.scrollWidth<=innerWidth", "Initial overflow")
        evaluate("document.querySelector('[data-private-action=new-deck]').click();document.getElementById('privateDeckTitle').value='Vectors <img src=x onerror=alert(1)>';document.getElementById('privateDeckWeek').value='1';document.getElementById('privateDeckForm').requestSubmit()")
        assert_js("!document.getElementById('privateDeckDialog').open && document.querySelectorAll('.private-deck').length===1 && !document.querySelector('.private-deck img')", "Deck creation / HTML escaping")
        evaluate("document.querySelector('[data-private-action=new-card]').click();document.getElementById('privateCardQuestion').value='What is a vector?';document.getElementById('privateCardAnswer').value='A quantity with magnitude and direction. <script>not executed</script>';document.getElementById('privateCardForm').requestSubmit()")
        assert_js("document.querySelectorAll('.private-card-row').length===1 && !document.getElementById('privateCardDialog').open", "Card save")
        evaluate("document.querySelector('[data-private-action=edit-card]').click();document.getElementById('privateCardAnswer').value='Magnitude and direction; velocity is an example.';document.getElementById('privateCardForm').requestSubmit()")
        assert_js("JSON.parse(localStorage.getItem(PrivateFlashcards.KEY)).decks[0].cards[0].answer.includes('velocity')", "Card edit")
        command("Page.reload")
        time.sleep(.6)
        assert_js("document.querySelectorAll('.private-deck').length===1", "Persistence after reload")
        evaluate("document.querySelector('[data-private-action=review]').click()")
        assert_js("document.getElementById('privateReviewDialog').open && document.getElementById('privateAnswerArea').hidden", "Answer must start hidden")
        evaluate("document.querySelector('[data-private-action=reveal]').click()")
        assert_js("!document.getElementById('privateAnswerArea').hidden && document.getElementById('privateReviewAnswer').textContent.includes('velocity')", "Reveal answer")
        assert_js("document.getElementById('privateReviewDialog').scrollWidth<=document.getElementById('privateReviewDialog').clientWidth", "Review dialog overflow")
        capture("review")
        evaluate("document.querySelector('[data-private-rating=good]').click()")
        assert_js("document.getElementById('privateReviewTitle').textContent==='Practice complete' && JSON.parse(localStorage.getItem(PrivateFlashcards.KEY)).decks[0].cards[0].progress.interval_days===1", "Rating must save progress")
        evaluate("document.getElementById('privateReviewDialog').close();window.backup=new PrivateFlashcards.Store(localStorage).backup();window.savedBlob='';window.originalCreate=URL.createObjectURL;URL.createObjectURL=blob=>{window.savedBlob=blob;return originalCreate(blob);};HTMLAnchorElement.prototype.click=function(){window.downloadName=this.download;};document.querySelector('[data-private-action=export]').click()")
        assert_js("(async()=>savedBlob instanceof Blob && JSON.parse(await savedBlob.text()).format===PrivateFlashcards.FORMAT && downloadName.startsWith('studyarchive-private-flashcards-'))()", "Download backup")
        evaluate("document.querySelector('[data-private-action=delete-deck]').click()")
        assert_js("document.querySelectorAll('.private-deck').length===0", "Delete deck confirmation")
        evaluate("window.files=new DataTransfer();files.items.add(new File([backup],'private-backup.json',{type:'application/json'}));document.getElementById('privateImportInput').files=files.files;document.getElementById('privateImportInput').dispatchEvent(new Event('change'))")
        time.sleep(.2)
        assert_js("document.querySelectorAll('.private-deck').length===1", "Restore backup")
        evaluate("window.files=new DataTransfer();files.items.add(new File(['not a backup'],'bad.json'));document.getElementById('privateImportInput').files=files.files;document.getElementById('privateImportInput').dispatchEvent(new Event('change'))")
        time.sleep(.2)
        assert_js("document.querySelectorAll('.private-deck').length===1 && document.getElementById('privateMessage').textContent.includes('not valid JSON')", "Invalid import must preserve cards")
        evaluate("document.getElementById('privateCourseFilter').value='STA 111';document.getElementById('privateCourseFilter').dispatchEvent(new Event('change'))")
        assert_js("document.querySelectorAll('.private-deck').length===0", "Course filter")
        evaluate("document.getElementById('privateCourseFilter').value='';document.getElementById('privateCourseFilter').dispatchEvent(new Event('change'));document.getElementById('privateFlashcards').scrollIntoView({block:'start'})")
        assert_js("document.documentElement.scrollWidth<=innerWidth", "Final overflow")
        capture("decks")
        assert posts == [], f"Private content sent to server: {posts}"
        print(f"OK {width}px: create/edit, reload persistence, reveal/review, export/import, invalid backup, delete, filtering, XSS safety, no HTTP writes", flush=True)
    try:
        _json_request(f"http://127.0.0.1:9226/json/close/{target['id']}")
    except json.JSONDecodeError:
        pass


try:
    _wait_for_debugger(9226)
    sizes = [(390, 844)] if "--mobile-only" in sys.argv else [(1440, 1050), (390, 844)]
    for width, height in sizes:
        check(width, height)
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    server.shutdown()
    assert profile.resolve().is_relative_to(scratch.resolve())
    shutil.rmtree(profile, ignore_errors=True)
