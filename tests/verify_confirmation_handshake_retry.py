from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402


class Recorder:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class Worker:
    original_calls = 0

    def __init__(self, url, payload=None):
        self.url = url
        self.payload = payload or {"quote_id": "Q-RETRY"}
        self.succeeded = Recorder()
        self.failed = Recorder()
        self.sleeps = []

    def run(self):
        type(self).original_calls += 1

    def msleep(self, value):
        self.sleeps.append(value)


layout_refresh._install_quote_api_worker_diagnostics({
    "ApiWorker": Worker,
    "api_headers": lambda has_body=False: (
        {"Content-Type": "application/json"} if has_body else {}
    ),
})


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


attempts = []


def succeeds_after_two_handshake_timeouts(_request, timeout=0):
    attempts.append(timeout)
    if len(attempts) < 3:
        raise urllib.error.URLError(TimeoutError("The handshake operation timed out"))
    return Response({"dry_run": True, "confirmed": True})


original_urlopen = layout_refresh.urllib.request.urlopen
layout_refresh.urllib.request.urlopen = succeeds_after_two_handshake_timeouts
try:
    worker = Worker("https://quote.test/api/quotes/confirm-check")
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

assert attempts == [layout_refresh.CONFIRM_REQUEST_TIMEOUT_SECONDS] * 3
assert worker.attempt_count == 3
assert worker.sleeps == list(layout_refresh.CONFIRM_REQUEST_RETRY_DELAYS_MS)
assert worker.succeeded.values == [{"dry_run": True, "confirmed": True}]
assert worker.failed.values == []


commit_attempts = []


def commit_after_handshake_timeout(_request, timeout=0):
    commit_attempts.append(timeout)
    if len(commit_attempts) == 1:
        raise urllib.error.URLError(TimeoutError("The handshake operation timed out"))
    return Response({"confirmed": True, "history_items": 1})


layout_refresh.urllib.request.urlopen = commit_after_handshake_timeout
try:
    worker = Worker("https://quote.test/api/quotes/confirm")
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

assert len(commit_attempts) == 2
assert worker.succeeded.values == [{"confirmed": True, "history_items": 1}]
assert worker.failed.values == []


def always_handshake_timeout(_request, timeout=0):
    assert timeout == layout_refresh.CONFIRM_REQUEST_TIMEOUT_SECONDS
    raise urllib.error.URLError(TimeoutError("The handshake operation timed out"))


layout_refresh.urllib.request.urlopen = always_handshake_timeout
try:
    worker = Worker("https://quote.test/api/quotes/confirm-check")
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

assert worker.attempt_count == layout_refresh.CONFIRM_REQUEST_MAX_ATTEMPTS
assert worker.succeeded.values == []
assert worker.failed.values == [
    "网络安全连接超时，系统已自动重试仍未成功，请检查网络后再次确认报价。"
]


ordinary = Worker("https://quote.test/api/products/catalog")
ordinary.run()
assert Worker.original_calls == 1

print("quote confirmation TLS retry passed")
