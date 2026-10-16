from types import SimpleNamespace
from unittest.mock import patch

from desktop_client.quote_diagnostics import (
    build_report, diagnostic_endpoint, record_event, submit_report,
)


class Control:
    def __init__(self, value):
        self._value = value

    def text(self):
        return self._value

    def currentText(self):
        return self._value

    def currentData(self):
        return self._value

    def value(self):
        return self._value


window = SimpleNamespace(
    scheme2_order_number=Control("ORDER-1"),
    scheme2_company=Control("测试客户"),
    product_combo=Control("JM"),
    quote_spec_edit=Control("1200*400*1400"),
    quantity_spin=Control(2),
    material_combo=Control("SECC"),
    _quote_progress_request_id="req-123",
)
record_event(window, "attachment_price_changed", item="风机", price=120,
             message="无法读取 C:/private/drawing.pdf")
item = {"product_code": "JM", "model_code": "JM-1200", "specification": "1200*400*1400",
        "formula": {"material_cost": 473.98, "api_key": "SECRET", "auxiliary_cost": 100},
        "quote_display": {"unit_price": 1200, "total": 2400, "discount": 0.75},
        "attachments": [{"item_name": "风机", "quantity": 4, "unit_price": 120}],
        "source_path": "C:/private/drawing.pdf", "final_remark": "token=SECRET"}
report = build_report(window, [item], client_version="2026.10.16.01")
assert report["quote_items"][0]["model_code"] == "JM-1200"
assert report["quote_items"][0]["formula"]["material_cost"] == 473.98
assert report["quote_items"][0]["attachments"][0]["unit_price"] == 120
assert report["quote_items"][0]["quote_display"] == {
    "unit_price": 1200, "total": 2400, "discount": 0.75}
assert "api_key" not in report["quote_items"][0]["formula"]
assert "source_path" not in report["quote_items"][0]
assert report["quote_items"][0]["final_remark"] == "token=[已隐藏]"
assert report["events"][0]["action"] == "attachment_price_changed"
assert "private" not in report["events"][0]["details"]["message"]
assert diagnostic_endpoint("https://quote.example/api/quotes/calculate-dual") == "https://quote.example/api/diagnostics/reports"
try:
    diagnostic_endpoint("http://quote.example/api/quotes/calculate-dual")
    raise AssertionError("remote HTTP endpoint was allowed")
except ValueError:
    pass

class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return b'{"submitted":true,"report_id":"report-1"}'


with patch("desktop_client.quote_diagnostics.request.urlopen", return_value=Response()) as upload:
    report_id = submit_report("https://quote.example/api/quotes/calculate-dual",
                              {"X-AI-Quote-Key": "private-key", "Authorization": "not-forwarded"}, report)
    assert report_id == "report-1"
    sent = upload.call_args.args[0]
    assert sent.get_header("X-ai-quote-key") == "private-key"
    assert sent.get_header("Authorization") is None

print("quote diagnostics tests passed")
