from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import re
import sys
import urllib.request


CODE = sys.argv[1]
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\client_config.json")
ORACLE_PATH = Path(__file__).with_name("excel-oracle-two-dimensions.json")


def calculator_class():
    source = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "FormulaDatabaseCalculator")
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"math": math, "re": re}
    exec(compile(module, "FormulaDatabaseCalculator", "exec"), namespace)
    return namespace["FormulaDatabaseCalculator"]


def source_code(family: str, single: int, double: int) -> str:
    if family in ("JK", "JM"):
        return family
    if family == "JA":
        return "JA_SINGLE"
    return f"{family}_{'SINGLE' if single > 0 else 'DOUBLE'}"


config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
base = str(config["api_url"]).split("/api/", 1)[0].rstrip("/")
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept-Encoding": "identity",
    "Connection": "close",
}
if config.get("api_key"):
    headers["X-AI-Quote-Key"] = str(config["api_key"])
request = urllib.request.Request(
    base + "/api/quotes/formula-template",
    data=json.dumps({"product_code": CODE}).encode("utf-8"),
    headers=headers,
    method="POST",
)
with urllib.request.urlopen(request, timeout=90) as response:
    payload = json.loads(response.read().decode("utf-8"))

calculator = calculator_class()()
calculator.load_template(payload)
oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8-sig"))["results"]
rows = []
for expected in oracle:
    family = expected["family"]
    if expected["doors"] == "-":
        single, double = 1, 0
    else:
        single, double = (int(value) for value in expected["doors"].split("/"))
    if source_code(family, single, double) != CODE:
        continue
    calculated = calculator.calculate(
        CODE,
        expected["width_mm"], expected["height_mm"], expected["depth_mm"],
        single, double,
    )
    weight, area = (float(value) for value in calculated)
    expected_weight = float(expected["weight_kg"])
    expected_area = float(expected["area_m2"])
    rows.append({
        "dimension": expected["dimension"],
        "family": family,
        "doors": expected["doors"],
        "weight_delta": weight - expected_weight,
        "area_delta": area - expected_area,
        "display": [round(weight, 1), round(area, 1)],
        "excel_display": [expected["display_weight_kg"], expected["display_area_m2"]],
        "pass": math.isclose(weight, expected_weight, abs_tol=1e-8)
        and math.isclose(area, expected_area, abs_tol=1e-8),
    })

print(json.dumps({
    "template_code": CODE,
    "case_count": len(rows),
    "pass_count": sum(row["pass"] for row in rows),
    "failures": [row for row in rows if not row["pass"]],
}, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(row["pass"] for row in rows) else 1)
