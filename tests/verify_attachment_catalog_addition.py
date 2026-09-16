"""Offline contracts for adding an attachment to the configured catalogue API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402


class Owner:
    api_url = "https://example.invalid/api/quotes/calculate-dual"


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "saved": True,
                "created": True,
                "attachment_price_id": 999,
                "attachment_contract": 2,
                "data_version": "fixture-v2",
            }
        ).encode("utf-8")


captured = {}
original_urlopen = layout_refresh.urllib.request.urlopen


def fake_urlopen(request, timeout):
    captured["request"] = request
    captured["timeout"] = timeout
    return Response()


payload = {
    "category_level1": "其他附件",
    "item_name": "测试附件",
    "price": 12.5,
}
try:
    layout_refresh.urllib.request.urlopen = fake_urlopen
    result = layout_refresh._save_attachment_catalog(
        Owner(),
        payload,
        {"api_headers": lambda has_body: {
            "Content-Type": "application/json; charset=utf-8",
            "X-AI-Quote-Key": "test-key" if has_body else "",
        }},
    )
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

request = captured["request"]
assert request.full_url == "https://example.invalid/api/attachments/catalog"
assert request.method == "POST"
assert captured["timeout"] == 60
assert json.loads(request.data.decode("utf-8")) == payload
assert request.headers["X-ai-quote-key"] == "test-key"
assert result["saved"] is True
assert result["attachment_contract"] == 2
assert result["data_version"] == "fixture-v2"

print("Attachment catalogue addition contracts passed")
