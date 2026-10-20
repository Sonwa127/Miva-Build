"""Headless-browser smoke test that reports console and failed-request errors."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
BASE_URL = "http://127.0.0.1:8000"
PAGES = ["/", "/courses", "/resources", "/ask", "/study", "/admin/login"]


def _json_request(url: str, method: str = "GET", timeout: float = 5) -> dict:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _wait_for_debugger(port: int) -> None:
    for _ in range(50):
        try:
            _json_request(f"http://127.0.0.1:{port}/json/version", timeout=0.2)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Chrome DevTools endpoint did not start")


def _check_page(port: int, path: str) -> list[str]:
    target_url = f"{BASE_URL}{path}"
    target = _json_request(
        f"http://127.0.0.1:{port}/json/new?about:blank",
        method="PUT",
    )
    errors: list[str] = []
    requests: dict[str, str] = {}
    action_ids: set[int] = set()
    command_id = 0
    interactions_sent = False

    with connect(target["webSocketDebuggerUrl"], open_timeout=5) as socket:
        for method in ("Runtime.enable", "Log.enable", "Network.enable", "Page.enable"):
            command_id += 1
            socket.send(json.dumps({"id": command_id, "method": method}))
        command_id += 1
        socket.send(json.dumps({"id": command_id, "method": "Page.navigate", "params": {"url":target_url}}))

        deadline = time.monotonic() + 8
        loaded_at: float | None = None
        while time.monotonic() < deadline:
            if loaded_at and not interactions_sent and time.monotonic() - loaded_at > 0.5:
                expressions: list[str] = []
                if path == "/courses":
                    expressions.append(
                        "document.getElementById('courseSort').value='name'; "
                        "document.getElementById('courseSort').dispatchEvent(new Event('change')); filterCourses()"
                    )
                elif path == "/ask":
                    expressions.append("document.getElementById('qaQueryInput').value='What topics are in this reading?'")
                elif path == "/study":
                    expressions.append("setDeckFilter('all'); scrollToGenerator()")
                elif path.startswith("/viewer/"):
                    expressions.append(
                        "document.getElementById('fitWidth').click(); document.getElementById('fitPage').click(); "
                        "document.getElementById('nextPage').click(); document.getElementById('previousPage').click()"
                    )
                for expression in expressions:
                    command_id += 1
                    action_ids.add(command_id)
                    socket.send(json.dumps({
                        "id": command_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": expression, "awaitPromise": True},
                    }))
                interactions_sent = True
            try:
                event = json.loads(socket.recv(timeout=0.5))
            except TimeoutError:
                if loaded_at and time.monotonic() - loaded_at > 2:
                    break
                continue

            method = event.get("method", "")
            params = event.get("params", {})
            if event.get("id") in action_ids:
                detail = event.get("result", {}).get("exceptionDetails")
                if detail:
                    errors.append(f"interaction exception: {detail.get('text', 'unknown error')}")
            if method == "Page.loadEventFired":
                loaded_at = time.monotonic()
            elif method == "Network.requestWillBeSent":
                requests[params.get("requestId", "")] = params.get("request", {}).get("url", "")
            elif method == "Runtime.exceptionThrown":
                detail = params.get("exceptionDetails", {})
                errors.append(f"JS exception: {detail.get('text', 'unknown error')}")
            elif method == "Runtime.consoleAPICalled" and params.get("type") in {"error", "warning"}:
                values = [str(arg.get("value", arg.get("description", ""))) for arg in params.get("args", [])]
                errors.append(f"console.{params['type']}: {' '.join(values)}")
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                if entry.get("level") in {"error", "warning"}:
                    location = f" [{entry['url']}]" if entry.get("url") else ""
                    errors.append(f"browser {entry.get('level')}: {entry.get('text', '')}{location}")
            elif method == "Network.loadingFailed" and not params.get("canceled"):
                failed_url = requests.get(params.get("requestId", ""), "unknown URL")
                errors.append(
                    f"request failed: {params.get('errorText', 'unknown')} "
                    f"({params.get('type', 'resource')}) [{failed_url}]"
                )
            elif method == "Network.responseReceived" and params.get("response", {}).get("status", 200) >= 400:
                response = params["response"]
                errors.append(f"HTTP {response['status']}: {response.get('url', '')}")


    try:
        _json_request(f"http://127.0.0.1:{port}/json/close/{target['id']}")
    except Exception:
        pass
    return list(dict.fromkeys(errors))


def main() -> int:
    if not CHROME.is_file():
        print(f"Chrome not found: {CHROME}")
        return 2

    port = 9223
    scratch = Path(__file__).resolve().parent / ".test-runs"
    scratch.mkdir(exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="browser-", dir=scratch))
    process = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        _wait_for_debugger(port)
        pages = list(PAGES)
        courses = _json_request(f"{BASE_URL}/api/courses")
        documents = _json_request(f"{BASE_URL}/api/documents")
        pages.extend(f"/courses/{course['id']}" for course in courses)
        pages.extend(f"/viewer/{document['doc_id']}?page=1" for document in documents)

        failures = 0
        for path in pages:
            errors = _check_page(port, path)
            if errors:
                failures += len(errors)
                print(f"FAIL {path}")
                for error in errors:
                    print(f"  - {error}")
            else:
                print(f"OK   {path}")
        return 1 if failures else 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
