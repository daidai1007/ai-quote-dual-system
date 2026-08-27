from __future__ import annotations

import json
import ast
import math
from pathlib import Path
import re
import urllib.request
import sys


config_path = Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\client_config.json")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
base = str(config["api_url"]).split("/api/", 1)[0].rstrip("/")
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept-Encoding": "identity",
    "Connection": "close",
}
if config.get("api_key"):
    headers["X-AI-Quote-Key"] = str(config["api_key"])
product_code = sys.argv[1] if len(sys.argv) > 1 else "JS_SINGLE"
request = urllib.request.Request(
    base + "/api/quotes/formula-template",
    data=json.dumps({"product_code": product_code}).encode("utf-8"),
    headers=headers,
    method="POST",
)
with urllib.request.urlopen(request, timeout=90) as response:
    payload = json.loads(response.read().decode("utf-8"))
rules = payload["template"]["rules"]
row = next((item for item in rules if int(item["source_row_no"]) == 11), rules[0])
raw = row.get("raw_rule") or {}
values = raw.get("values") or []
print(json.dumps({
    "template_code": payload["template"].get("template_code"),
    "rule_count": len(rules),
    "sample_source_row_no": row.get("source_row_no"),
    "sample_part_name": row.get("part_name"),
    "sample_surface_treatment": row.get("surface_treatment"),
    "sample_include_material_cost": row.get("include_material_cost"),
    "raw_part_name_E": values[1] if len(values) > 1 else None,
    "raw_treatment_N": values[10] if len(values) > 10 else None,
    "raw_values_count": len(values),
    "raw_formulas_count": len(raw.get("formulas") or []),
}, ensure_ascii=False, indent=2))

root = Path(__file__).resolve().parents[2]
source = (root / "desktop_client" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(source)
calculator_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "FormulaDatabaseCalculator"
)
module = ast.fix_missing_locations(ast.Module(body=[calculator_node], type_ignores=[]))
namespace = {"math": math, "re": re}
exec(compile(module, "FormulaDatabaseCalculator", "exec"), namespace)
calculator = namespace["FormulaDatabaseCalculator"]()
calculator.load_template(payload)
weight, area = calculator.calculate(product_code, 800, 300, 1800, 1, 0)
print(json.dumps({
    "live_template_current_source": {"weight_kg": weight, "area_m2": area},
    "display_one_decimal": {"weight_kg": round(weight, 1), "area_m2": round(area, 1)},
}, ensure_ascii=False, indent=2))
