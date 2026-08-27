from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.request
import time


ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_ROOT))
os.environ["AI_QUOTE_V3_CORE_ROOT"] = str(
    ROOT.parent / "AIQuoteDualSystem" / "_internal" / "v3_core"
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import layout_refresh
import v3_launcher


config = json.loads(
    (ROOT.parent / "AIQuoteDualSystem" / "client_config.json").read_text(
        encoding="utf-8-sig"
    )
)
os.environ["AI_QUOTE_API_URL"] = str(config["api_url"])
os.environ["AI_QUOTE_API_KEY"] = str(config.get("api_key") or "")
base = str(config["api_url"]).split("/api/", 1)[0].rstrip("/")
headers = {"Content-Type": "application/json; charset=utf-8"}
if config.get("api_key"):
    headers["X-AI-Quote-Key"] = str(config["api_key"])
request = urllib.request.Request(
    base + "/api/quotes/formula-template",
    data=json.dumps({"product_code": "JP_SINGLE"}).encode("utf-8"),
    headers=headers,
    method="POST",
)
with urllib.request.urlopen(request, timeout=90) as response:
    template = json.loads(response.read().decode("utf-8"))

namespace = v3_launcher.load_v3_namespace()
calculator = namespace["FormulaDatabaseCalculator"]()
calculator.load_template(template)


class Combo:
    def __init__(self, value):
        self.value = value

    def currentData(self):
        return self.value


window = SimpleNamespace(
    ganged_cabinets=[
        {
            "width_mm": 600,
            "depth_mm": 300,
            "height_mm": 1800,
            "single_door_count": 1,
            "double_door_count": 0,
        },
        {
            "width_mm": 900,
            "depth_mm": 300,
            "height_mm": 1800,
            "single_door_count": 1,
            "double_door_count": 0,
        },
    ],
    product_combo=Combo("JP"),
    product_catalog={
        "JP": {
            "codes": {"SINGLE": "JP_SINGLE", "DOUBLE": "JP_DOUBLE"},
            "method": "formula",
        }
    },
    material_combo=Combo("SECC"),
    coating_combo=Combo("橘纹"),
    quote_date=None,
    formula_calculator=calculator,
)

payloads, weight_total, area_total = layout_refresh._build_ganged_quote_payloads(window)
print(
    json.dumps(
        {
            "payloads": [
                {
                    key: row.get(key)
                    for key in (
                        "product_code",
                        "model_code",
                        "width_mm",
                        "depth_mm",
                        "height_mm",
                        "base_material_weight_kg",
                        "product_area_m2",
                        "single_door_count",
                        "double_door_count",
                    )
                }
                for row in payloads
            ],
            "weight_total": weight_total,
            "area_total": area_total,
        },
        ensure_ascii=False,
        indent=2,
    )
)

from PySide6.QtWidgets import QApplication

namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication(sys.argv[:1])
main_window = namespace["MainWindow"]()
main_window.api_url.setText(str(config["api_url"]))
main_window.product_catalog = {
    "JP": {
        "codes": {"SINGLE": "JP_SINGLE", "DOUBLE": "JP_DOUBLE"},
        "method": "formula",
        "name": "JP",
    }
}
main_window.product_combo.blockSignals(True)
main_window.product_combo.clear()
main_window.product_combo.addItem("JP", "JP")
main_window.product_combo.blockSignals(False)
main_window.formula_calculator = calculator
main_window.ganged_cabinets = list(window.ganged_cabinets)
main_window.ganged_cabinet_count = 2
main_window.ganged_cabinet_specification = "(600+900)*300*1800"
main_window.attachments = []
main_window.set_door_counts(1, 0)
main_window.calculate_button.click()
deadline = time.monotonic() + 70
while time.monotonic() < deadline:
    app.processEvents()
    if main_window.current_result or (
        main_window.calculate_button.isEnabled()
        and getattr(main_window, "worker", None) is not None
        and not main_window.worker.isRunning()
    ):
        break
    time.sleep(0.05)
ui_result = main_window.current_result or {}
print(
    json.dumps(
        {
            "button_reenabled": main_window.calculate_button.isEnabled(),
            "has_result": bool(ui_result),
            "risk_text": main_window.risk_label.text(),
            "formula_total": (ui_result.get("formula") or {}).get("total_cost"),
            "quick_total": (ui_result.get("quick") or {}).get("total_cost"),
        },
        ensure_ascii=False,
        indent=2,
    )
)
main_window.close()

responses = []
for payload in payloads:
    quote_request = urllib.request.Request(
        str(config["api_url"]),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(quote_request, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    responses.append(
        {
            "product_code": payload["product_code"],
            "model_code": payload["model_code"],
            "formula_total": (result.get("formula_cost") or {}).get("total_cost"),
            "quick_total": (result.get("quick_quote") or {}).get("total_cost"),
            "quick_base": (result.get("quick_quote") or {}).get("base_price"),
            "risks": result.get("risk_flags") or [],
        }
    )
print(json.dumps({"api_responses": responses}, ensure_ascii=False, indent=2))

aggregated = []
failed = []
worker = layout_refresh._GangedQuoteWorker(
    str(config["api_url"]),
    payloads,
    0,
    lambda has_json_body=False: headers,
    weight_total,
    area_total,
)
worker.succeeded.connect(aggregated.append)
worker.failed.connect(failed.append)
worker.run()
summary = aggregated[0] if aggregated else {}
print(
    json.dumps(
        {
            "worker_failed": failed,
            "formula_total": (summary.get("formula_cost") or {}).get("total_cost"),
            "quick_total": (summary.get("quick_quote") or {}).get("total_cost"),
            "formula_weight_kg": summary.get("ganged_weight_kg"),
            "formula_area_m2": summary.get("ganged_area_m2"),
        },
        ensure_ascii=False,
        indent=2,
    )
)
