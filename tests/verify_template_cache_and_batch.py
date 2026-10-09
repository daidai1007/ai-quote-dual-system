from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
import layout_refresh as client


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode("utf-8")


url = "https://cache.test/api/quotes/formula-template"
headers = lambda _json: {"x-ai-quote-key": "test-one"}
calls = []
version = "v1"


def templates(request, timeout=0):
    assert timeout == client.FORMULA_TEMPLATE_REQUEST_TIMEOUT_SECONDS
    body = json.loads(request.data)
    calls.append((request.full_url, body))
    if body.get("known_version") == version:
        return Response({"template_version": version, "not_modified": True, "template": None})
    return Response({"template_version": version, "not_modified": False,
                     "template": {"template_code": body["product_code"], "rules": [{"formula": version}]}})


original = client.urllib.request.urlopen
client._FORMULA_TEMPLATE_CACHE.clear()
try:
    client.urllib.request.urlopen = templates
    first = client._fetch_formula_template(url, "JP_SINGLE", headers)
    first["template"]["rules"].clear()
    second = client._fetch_formula_template(url, "JP_SINGLE", headers)
    assert second["template"]["rules"] == [{"formula": "v1"}]
    assert len(calls) == 1, "dimension changes must reuse the product template"
    assert client._fresh_formula_template(url, "JP_SINGLE", headers) is not None

    window = SimpleNamespace(base_url=lambda: "https://cache.test", _formula_template_headers_factory=headers)
    client._record_window_template(window, "JP_SINGLE", second, headers)
    assert not client._window_formula_template_stale(window, "JP_SINGLE")
    window.base_url = lambda: "https://other.test"
    assert client._window_formula_template_stale(window, "JP_SINGLE")
    window.base_url = lambda: "https://cache.test"

    entry = next(iter(client._FORMULA_TEMPLATE_CACHE.values()))
    entry["checked_at"] = float("-inf")
    assert client._window_formula_template_stale(window, "JP_SINGLE")
    unchanged = client._fetch_formula_template(url, "JP_SINGLE", headers)
    assert calls[-1][1]["known_version"] == "v1"
    assert unchanged["template"]["rules"] == second["template"]["rules"]
    assert not client._window_formula_template_stale(window, "JP_SINGLE")

    entry["checked_at"] = float("-inf")
    version = "v2"
    updated = client._fetch_formula_template(url, "JP_SINGLE", headers)
    assert updated["template"]["rules"] == [{"formula": "v2"}]
    assert client._window_formula_template_stale(window, "JP_SINGLE"), "loaded old calculator must be refreshed"
    client._record_window_template(window, "JP_SINGLE", updated, headers)
    assert not client._window_formula_template_stale(window, "JP_SINGLE")

    client._fetch_formula_template(url, "JP_DOUBLE", headers)
    client._fetch_formula_template("https://other.test/api/quotes/formula-template", "JP_SINGLE", headers)
    client._fetch_formula_template(url, "JP_SINGLE", lambda _json: {"x-ai-quote-key": "test-two"})
    assert len(calls) == 6, "product, endpoint and credential scope must be isolated"

    # A validation failure is never allowed to produce a stale cached quote.
    entry["checked_at"] = float("-inf")
    client.urllib.request.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout"))
    try:
        client._fetch_formula_template(url, "JP_SINGLE", headers)
    except TimeoutError:
        pass
    else:
        raise AssertionError("stale template silently used")
    assert client._fresh_formula_template(url, "JP_SINGLE", headers) is None

    # Concurrent single/ganged requests for the same product download once.
    client._FORMULA_TEMPLATE_CACHE.clear()
    entered, release = threading.Event(), threading.Event()
    calls.clear()
    def blocked(request, timeout=0):
        entered.set()
        assert release.wait(2)
        return templates(request, timeout)
    client.urllib.request.urlopen = blocked
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(client._fetch_formula_template, url, "JP_SINGLE", headers)
        assert entered.wait(2)
        b = pool.submit(client._fetch_formula_template, url, "JP_SINGLE", headers)
        release.set()
        assert a.result() == b.result()
    assert len(calls) == 1

    # Single and ganged template workers share the same versioned cache.
    got = []
    worker = client._GangedFormulaTemplateWorker("https://cache.test", ["JP_SINGLE"], headers)
    worker.succeeded.connect(got.append)
    worker.run()
    assert len(calls) == 1 and len(got[0]) == 1

    # One HTTP request includes all children and the independently indexed bases.
    cabinets = [{"quote_id": "one", "width_mm": 1000}, {"quote_id": "two", "width_mm": 800}]
    attachment = {"attachments": [{"ganged_cabinet_index": 0}, {"ganged_cabinet_index": 1}]}
    aggregate = {"ganged_batch_contract": 1, "formula_cost": {"corrected_material_weight_kg": 216},
                 "quick_quote": {"total_cost": 3600}, "ganged_cabinet_results": [{}, {}], "attachment_contract": 2}
    requests = []
    def batch_request(request, timeout=0):
        assert request.full_url.endswith("/api/quotes/calculate-ganged")
        assert timeout == client.QUOTE_REQUEST_TIMEOUT_SECONDS
        requests.append(json.loads(request.data))
        return Response(aggregate)
    client.urllib.request.urlopen = batch_request
    got, errors = [], []
    worker = client._GangedQuoteWorker("https://cache.test/api/quotes/calculate-dual", cabinets,
        100, headers, 216, 18, attachment_payload=attachment)
    worker.succeeded.connect(got.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert not errors, errors
    assert got == [aggregate] and len(requests) == 1
    assert requests[0]["cabinets"] == cabinets
    assert requests[0]["attachment_payload"] == attachment

    # Real calculation failures must not trigger duplicate legacy writes.
    requests.clear()
    def broken_batch(request, timeout=0):
        requests.append(request.full_url)
        raise client.urllib.error.HTTPError(request.full_url, 500, "failure", {}, None)
    client.urllib.request.urlopen = broken_batch
    got.clear()
    worker.run()
    assert len(requests) == 1 and not got and errors
finally:
    client.urllib.request.urlopen = original
    client._FORMULA_TEMPLATE_CACHE.clear()

print("PASS: versioned template cache, freshness/invalidation, scope isolation, single-flight and one-request ganged batch")
