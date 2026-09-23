from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "AI_QUOTE_V3_CORE_ROOT",
    str(ROOT.parent / "AIQuoteDualSystem" / "_internal" / "v3_core"),
)

import v3_launcher


def api_base(config):
    return str(config["api_url"]).split("/api/", 1)[0].rstrip("/")


def request_json(base, key, path, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=body,
        headers={"X-AI-Quote-Key": key, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode("utf-8", errors="replace")) from error
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(2)


DIMENSIONS = [
    (600, 1800, 400), (800, 1800, 600), (1000, 1800, 600), (1200, 1800, 600),
    (600, 2000, 600), (800, 2000, 600), (1000, 2000, 600), (1200, 2000, 600),
    (600, 2000, 800), (800, 2000, 800), (1000, 2000, 800), (1200, 2000, 800),
    (600, 2200, 600), (800, 2200, 600), (1000, 2200, 600), (1200, 2200, 600),
]

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
base, key = api_base(config), str(config.get("api_key") or "").strip()
namespace = v3_launcher.load_v3_namespace()
calculators = {}
for code in ("JP_SINGLE", "JP_DOUBLE"):
    calculator = namespace["FormulaDatabaseCalculator"]()
    calculator.load_template(request_json(base, key, "/api/quotes/formula-template", {"product_code": code}))
    calculators[code] = calculator

results = []
for width, height, depth in DIMENSIONS:
    product_code = "JP_DOUBLE" if width > 800 else "JP_SINGLE"
    single, double = (0, 1) if width > 800 else (1, 0)
    weight, area = calculators[product_code].calculate(product_code, width, height, depth, single, double)
    payload = {
        "quote_id": f"CHECK-{uuid4().hex}", "product_code": product_code,
        "model_code": f"{width}×{depth}×{height}", "material_code": "SUS304",
        "width_mm": width, "height_mm": height, "depth_mm": depth,
        "base_material_weight_kg": weight, "product_area_m2": area,
        "coating_type": "无", "variant_code": "DOUBLE" if double else "SINGLE",
        "single_door_count": single, "double_door_count": double, "attachments": [],
        "material_unit_price_override": 16.0,
        "galvanized_sheet_unit_price_override": 4.55,
        "carbon_steel_unit_price_override": 4.2,
        "surface_treatment_unit_price_override": 0.0,
        "cabinet_body_thickness_mm": 1.5, "waste_factor": 1.2,
    }
    quote = request_json(base, key, "/api/quotes/calculate-dual", payload)
    formula = quote.get("formula_cost") or {}
    quick = quote.get("quick_quote") or {}
    results.append({
        "width": width, "height": height, "depth": depth,
        "cost": formula.get("total_cost"), "face": quick.get("total_cost"),
        "spray": formula.get("spray_cost"), "quick_match": quick.get("match_method"),
    })

print(json.dumps(results, ensure_ascii=False))
