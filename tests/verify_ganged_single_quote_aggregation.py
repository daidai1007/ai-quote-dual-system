from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402


class Combo:
    def __init__(self, value):
        self.value = value

    def currentData(self):
        return self.value


window = SimpleNamespace(
    ganged_cabinets=[
        {"width_mm": 800, "height_mm": 1800, "depth_mm": 800, "single_door_count": 1, "double_door_count": 0},
        {"width_mm": 800, "height_mm": 1800, "depth_mm": 800, "single_door_count": 1, "double_door_count": 0},
    ],
    product_combo=Combo("JP"),
    product_catalog={"JP": {"codes": {"SINGLE": "JP_SINGLE"}}},
    material_combo=Combo("SECC"),
    coating_combo=Combo("无"),
    quote_date=None,
    formula_calculator=SimpleNamespace(calculate=lambda *_args: (140.5, 7.1)),
    scheme2_defaults={
        "galvanized_price": 4.55,
        "carbon_price": 4.2,
        "stainless_price": 32.4,
        "surface_price": 26,
    },
)

payloads, weight, area = layout_refresh._build_ganged_quote_payloads(window)
assert len(payloads) == 2
assert weight == 281.0 and area == 14.2
for payload in payloads:
    assert (
        payload["width_mm"], payload["depth_mm"], payload["height_mm"]
    ) == (800.0, 800.0, 1800.0)
    assert payload["galvanized_sheet_unit_price_override"] == 4.55
    assert payload["carbon_steel_unit_price_override"] == 4.2
    assert payload["material_unit_price_override"] == 4.2
    assert payload["surface_treatment_unit_price_override"] == 0


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


child_results = [
    {
        "formula_cost": {
            "material_cost": 100, "auxiliary_cost": 20, "labor_cost": 30,
            "spray_cost": 40, "management_fee": 10, "attachment_fee": 0,
            "total_cost": 200, "product_area_m2": 7.1,
        },
        "quick_quote": {"base_price": 1000, "attachment_fee": 0, "total_cost": 1000, "dimension_distance": 0},
    },
    {
        "formula_cost": {
            "material_cost": 150, "auxiliary_cost": 30, "labor_cost": 45,
            "spray_cost": 60, "management_fee": 15, "attachment_fee": 0,
            "total_cost": 300, "product_area_m2": 7.1,
        },
        "quick_quote": {"base_price": 1200, "attachment_fee": 0, "total_cost": 1200, "dimension_distance": 0},
    },
]
requests = []


def urlopen(request, timeout=0):
    del timeout
    requests.append(json.loads(request.data.decode()))
    return Response(child_results[len(requests) - 1])


original_urlopen = layout_refresh.urllib.request.urlopen
layout_refresh.urllib.request.urlopen = urlopen
try:
    worker = layout_refresh._GangedQuoteWorker(
        "https://quote.test/api/quotes/calculate-dual",
        payloads,
        0,
        lambda _json: {"Content-Type": "application/json"},
        weight,
        area,
    )
    result = []
    worker.succeeded.connect(result.append)
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

assert len(requests) == 2 and len(result) == 1
aggregate = result[0]
assert aggregate["quick_quote"]["base_price"] == 2200
assert aggregate["quick_quote"]["total_cost"] == 2200
assert aggregate["formula_cost"]["material_cost"] == 250
assert aggregate["formula_cost"]["total_cost"] == 500
children = aggregate["formula_cost"]["ganged_cabinet_costs"]
assert len(children) == 2
assert children[0]["cabinet_index"] == 1
assert children[0]["model_code"]
assert (children[0]["width_mm"], children[0]["depth_mm"], children[0]["height_mm"]) == (800, 800, 1800)
assert children[0]["formula_cost"]["total_cost"] == 200
assert children[1]["cabinet_index"] == 2
assert children[1]["formula_cost"]["total_cost"] == 300

print("ganged single-cabinet aggregation passed")
