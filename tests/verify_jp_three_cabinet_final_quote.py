from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import layout_refresh  # noqa: E402
from ganged_cabinet_rules import parse_ganged_specification  # noqa: E402


SPECIFICATION = "（800+600+800）/800/（2000+100）"
parsed = parse_ganged_specification(SPECIFICATION)
assert parsed is not None
assert parsed["split_count"] == 3
assert parsed["widths_mm"] == [800.0, 600.0, 800.0]
assert parsed["depth_mm"] == 800.0
assert parsed["height_mm"] == 2000.0
assert parsed["base_height_mm"] == 100.0


class Combo:
    def __init__(self, value):
        self.value = value

    def currentData(self):
        return self.value


rows = []
for row in parsed["rows"]:
    rows.append({
        **row,
        "single_door_count": 1,
        "double_door_count": 0,
        "door_selection_mode": "automatic",
    })

window = SimpleNamespace(
    ganged_cabinets=rows,
    product_combo=Combo("JP"),
    product_catalog={"JP": {"codes": {"SINGLE": "JP_SINGLE"}}},
    material_combo=Combo("SECC"),
    coating_combo=Combo("无"),
    quote_date=None,
    formula_calculator=SimpleNamespace(
        calculate=lambda _code, width, _height, _depth, *_doors: (
            width / 10,
            width / 100,
        )
    ),
    scheme2_defaults={
        "galvanized_price": 4.55,
        "carbon_price": 4.2,
        "stainless_price": 32.4,
        "surface_price": 26,
    },
)

payloads, weight, area = layout_refresh._build_ganged_quote_payloads(window)
assert len(payloads) == 3
assert [item["model_code"] for item in payloads] == [
    "800×800×（2000+100）",
    "600×800×（2000+100）",
    "800×800×（2000+100）",
]
assert weight == 220.0
assert area == 22.0


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


child_results = []
for index, payload in enumerate(payloads, start=1):
    width = payload["width_mm"]
    child_results.append({
        "formula_cost": {
            "material_cost": width,
            "auxiliary_cost": 10 * index,
            "labor_cost": 20 * index,
            "spray_cost": 30 * index,
            "management_fee": 4 * index,
            "attachment_fee": 0,
            "total_cost": width + 64 * index,
            "product_area_m2": width / 100,
        },
        "quick_quote": {
            "base_price": width * 2,
            "attachment_fee": 0,
            "total_cost": width * 2,
            "dimension_distance": 0,
        },
    })

requests = []


def urlopen(request, timeout=0):
    del timeout
    if request.full_url.endswith("/api/quotes/calculate-ganged"):
        raise layout_refresh.urllib.error.HTTPError(request.full_url, 404, "old API", {}, None)
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
    results = []
    worker.succeeded.connect(results.append)
    worker.run()
finally:
    layout_refresh.urllib.request.urlopen = original_urlopen

assert len(requests) == 3 and len(results) == 1
aggregate = results[0]
assert aggregate["quick_quote"]["base_price"] == 4400
assert aggregate["formula_cost"]["material_cost"] == 2200
assert aggregate["formula_cost"]["total_cost"] == sum(
    item["formula_cost"]["total_cost"] for item in child_results
)


calls = []


def base_parser(text):
    calls.append(text)
    if "+" in str(text):
        return None
    return {"specification": str(text)}


scope = {"parse_review_specification": base_parser}
exec(
    "def original_add(window):\n"
    "    window.saved = parse_review_specification(window.specification)\n"
    "    return window.saved is not None\n",
    scope,
)
save_window = SimpleNamespace(specification=SPECIFICATION, saved=None)
assert layout_refresh._add_with_ganged_specification(
    save_window,
    scope["original_add"],
    rows,
    SPECIFICATION,
)
assert calls == ["800*800*2000"]


fixture = json.loads(
    (ROOT / "tests" / "fixtures" / "export_formula_cost_detail.json").read_text(
        encoding="utf-8"
    )
)
item = fixture["items"][0]
item.update({
    "source_pdf_name": "JP并柜验证.pdf",
    "product_family": "JP",
    "product_code": "JP_SINGLE",
    "model_code": SPECIFICATION,
    "specification": SPECIFICATION,
    "width_mm": 800,
    "depth_mm": 800,
    "height_mm": 2000,
    "formula": aggregate["formula_cost"],
    "quick": aggregate["quick_quote"],
    "ganged_cabinet_count": 3,
    "ganged_cabinets": rows,
})
fixture["items"] = [item]

with tempfile.TemporaryDirectory(prefix=".jp-ganged-final-quote-", dir=ROOT) as temp_dir:
    temp = Path(temp_dir)
    input_path = temp / "quote.json"
    output_path = temp / "quote.xlsx"
    input_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        ["node", str(ROOT / "export_dual_quote_workbook.mjs"), str(input_path), str(output_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert output_path.stat().st_size > 0
    with zipfile.ZipFile(output_path) as workbook:
        names = set(workbook.namelist())
        assert "xl/workbook.xml" in names
        xml = b"".join(
            workbook.read(name) for name in names if name.endswith(".xml")
        ).decode("utf-8", errors="ignore")
        assert SPECIFICATION in xml

print("JP three-cabinet final quote verification passed")
