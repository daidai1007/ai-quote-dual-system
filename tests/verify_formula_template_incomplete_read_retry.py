import http.client
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh

assert layout_refresh._formula_template_error_is_transient(http.client.IncompleteRead(b"", 1))

attempts = []
payloads = []
original_open = layout_refresh.urllib.request.urlopen
original_delays = layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS

class Response:
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps({"template": {"template_code": "JP_SINGLE"}}).encode()

def open_after_partial_read(_request, timeout=0):
    attempts.append(timeout)
    if len(attempts) == 1:
        raise http.client.IncompleteRead(b"", 1)
    return Response()

try:
    layout_refresh.urllib.request.urlopen = open_after_partial_read
    layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS = (0, 0)
    worker = layout_refresh._FormulaTemplateWorker("https://example.test/api/quotes/formula-template", "JP", lambda _json: {})
    worker.succeeded.connect(payloads.append)
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_open
    layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS = original_delays

assert len(attempts) == 2
assert payloads[0]["template"]["template_code"] == "JP_SINGLE"
print("PASS: formula template retries after IncompleteRead")
