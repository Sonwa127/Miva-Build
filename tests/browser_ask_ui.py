"""Isolated Chrome UI checks. Run manually: python tests/browser_ask_ui.py.

Uses rendered app HTML and mocked AI replies; never reads or modifies live data.
Screenshots go to ignored .test-runs; no cloud key or AI request is required.
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

with patch("archive.courses.list_courses", return_value=[SimpleNamespace(code="STA 111", name="Descriptive Statistics"), SimpleNamespace(code="PHY 101", name="Physics")]), patch("archive.config.LLM_PROVIDER", "offline"):
    with TestClient(app) as client:
        html = client.get("/ask?course_id=STA%20111").content


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "frontend"), **kwargs)

    def do_GET(self):
        if self.path.startswith("/ask"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


scratch = ROOT / ".test-runs"
scratch.mkdir(exist_ok=True)
profile = Path(tempfile.mkdtemp(prefix="ask-browser-", dir=scratch))
server = ThreadingHTTPServer(("127.0.0.1", 8012), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
process = subprocess.Popen([str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=9225", f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def check(width, height):
    target = _json_request("http://127.0.0.1:9225/json/new?about:blank", method="PUT")
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

        def screenshot(name):
            command("Runtime.evaluate", {"expression": "scrollTo(0,0)"})
            time.sleep(.3)
            data = command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
            (scratch / f"ask-{width}-{name}.png").write_bytes(base64.b64decode(data))

        command("Runtime.enable")
        command("Page.enable")
        command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        command("Page.navigate", {"url": "http://127.0.0.1:8012/ask"})
        time.sleep(1.5)
        assert evaluate("document.documentElement.scrollWidth <= innerWidth"), "Initial overflow"
        assert evaluate("document.getElementById('inputScopeLabel').textContent.includes('STA 111')")
        assert evaluate("document.querySelector('[data-prompt=explain]').click(); document.getElementById('qaQueryInput').value.includes('[concept]')")
        evaluate("document.getElementById('qaQueryInput').value=''")
        screenshot("welcome")
        evaluate("""window.calls=[]; window.nextResult={answer:'**Statistics** is the study of data. [2]\\n\\nIt helps us understand patterns.', sources:[{n:2,doc_id:'stats',page:38,title:'Descriptive Statistics – STA 111',text:'Statistics involves collecting, summarising, organising, analysing, and interpreting data.'},{n:4,doc_id:'week1',page:7,title:'Week 1 examples',text:'A population contains all members of a group; a sample contains a subset.'}],low_confidence:false,log_id:42}; window.api=async (url,method,payload)=>{calls.push({url,payload}); if(window.failNext && url.endsWith('/ask')){window.failNext=false;throw new Error('<img src=x onerror=alert(1)> Service unavailable');} if(url.endsWith('/ask'))return structuredClone(nextResult);return {status:'success'};};""")
        evaluate("document.getElementById('qaQueryInput').value='What is statistics? <img src=x onerror=alert(1)>'; document.getElementById('questionForm').requestSubmit()")
        time.sleep(.1)
        assert evaluate("document.querySelectorAll('.ask-answer').length===1 && !document.querySelector('.ask-question img')")
        assert evaluate("calls[0].payload.course_id==='STA 111' && document.querySelector('.ask-inline-citation').href.endsWith('/viewer/stats?page=38')")
        assert evaluate("document.querySelector('.ask-answer-body strong').textContent==='Statistics'")
        assert evaluate("document.querySelector('[data-source-index=\"1\"]').click(); document.querySelector('.ask-source-page').textContent==='Page 7'")
        assert evaluate("document.documentElement.scrollWidth <= innerWidth"), "Answer overflow"
        screenshot("answer")
        evaluate("nextResult={answer:'I could not find this in the course materials.',sources:[],low_confidence:true,log_id:77};document.getElementById('qaQueryInput').value='An unrelated question';document.getElementById('questionForm').requestSubmit()")
        time.sleep(.1)
        assert evaluate("document.querySelector('.ask-no-answer')!==null && !document.querySelector('.ask-source-excerpt') && document.getElementById('sourceCount').hidden")
        evaluate("document.querySelector('[data-feedback-id=\"1\"][data-rating=\"1\"]').click()")
        time.sleep(.1)
        assert evaluate("calls.at(-1).payload.query_log_id===42"), "Feedback attached to wrong answer"
        evaluate("document.querySelector('.ask-answer [data-source-answer]').click()")
        assert evaluate("document.querySelector('.ask-source-page').textContent==='Page 38'"), "Old sources not restored"
        evaluate("window.failNext=true;document.getElementById('qaQueryInput').value='Retry me';document.getElementById('questionForm').requestSubmit()")
        time.sleep(.1)
        assert evaluate("document.querySelector('.ask-error')!==null && !document.querySelector('.ask-error img') && document.getElementById('qaQueryInput').value==='Retry me' && !document.getElementById('sendQaBtn').disabled")
        evaluate("document.querySelector('.ask-error button').click()")
        time.sleep(.1)
        assert evaluate("!document.querySelector('.ask-error') && document.querySelectorAll('.ask-answer').length===3")
        evaluate("document.getElementById('clearChatBtn').click()")
        assert evaluate("document.getElementById('welcomeChatCard')!==null && !document.querySelector('.ask-answer') && !document.querySelector('.ask-source-excerpt')")
        evaluate("window.api=()=>new Promise(resolve=>window.releaseAnswer=resolve);document.getElementById('qaQueryInput').value='One request only';document.getElementById('questionForm').requestSubmit();document.getElementById('questionForm').requestSubmit()")
        assert evaluate("document.querySelectorAll('.ask-question').length===1 && document.getElementById('sendQaBtn').disabled"), "Duplicate request guard"
        evaluate("window.releaseAnswer(nextResult)")
        time.sleep(.1)
        assert evaluate("!document.getElementById('sendQaBtn').disabled")
        print(f"OK {width}px: prompts, citations, multiple sources, feedback IDs, empty/error/retry/reset states, XSS escaping, duplicate guard", flush=True)


try:
    _wait_for_debugger(9225)
    for width, height in [(1440, 1050), (390, 844), (768, 1024)]:
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
