from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = ROOT / "tests" / "verify_cloud_formula_door_matrix_readonly.py"
spec = importlib.util.spec_from_file_location("verify_formula", VERIFY_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

config_path = Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\client_config.json")
oracle_path = Path(__file__).with_name("excel-oracle-two-dimensions.json")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
base = module.api_base(config)
key = str(config.get("api_key") or "").strip()
calculator = module.load_calculator(ROOT)


def request_template_stable(product_code: str) -> dict:
    body = json.dumps({"product_code": product_code}).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if key:
        headers["X-AI-Quote-Key"] = key
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                base + "/api/quotes/formula-template", data=body,
                headers=headers, method="POST",
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            if attempt == 3:
                raise
            print(f"RETRY={product_code} {attempt}: {type(error).__name__}", flush=True)
            time.sleep(attempt)

template_codes = {
    code for codes in module.FAMILY_CODES.values() for code in codes.values()
} | set(module.SINGLE_CASE_CODES)
for code in sorted(template_codes):
    print(f"FETCH={code}", flush=True)
    calculator.load_template(request_template_stable(code))

oracle = json.loads(oracle_path.read_text(encoding="utf-8-sig"))
results = []
for expected in oracle["results"]:
    family = expected["family"]
    if family in module.SINGLE_CASE_CODES:
        code = family
        single, double = 1, 0
    else:
        single, double = (int(value) for value in expected["doors"].split("/"))
        code = module.selected_template(module.FAMILY_CODES[family], single, double)
    weight, area = calculator.calculate(
        code,
        expected["width_mm"],
        expected["height_mm"],
        expected["depth_mm"],
        single,
        double,
    )
    weight_delta = float(weight) - float(expected["weight_kg"])
    area_delta = float(area) - float(expected["area_m2"])
    display_weight = round(float(weight), 1)
    display_area = round(float(area), 1)
    status = "PASS" if (
        math.isclose(weight_delta, 0, abs_tol=1e-8)
        and math.isclose(area_delta, 0, abs_tol=1e-8)
        and display_weight == float(expected["display_weight_kg"])
        and display_area == float(expected["display_area_m2"])
    ) else "FAIL"
    results.append({
        "dimension": expected["dimension"],
        "family": family,
        "doors": expected["doors"],
        "template_code": code,
        "program_weight_kg": weight,
        "excel_weight_kg": expected["weight_kg"],
        "weight_delta": weight_delta,
        "program_area_m2": area,
        "excel_area_m2": expected["area_m2"],
        "area_delta": area_delta,
        "program_display_weight_kg": display_weight,
        "excel_display_weight_kg": expected["display_weight_kg"],
        "program_display_area_m2": display_area,
        "excel_display_area_m2": expected["display_area_m2"],
        "status": status,
    })
    print(f"CASE={expected['dimension']} {family} {expected['doors']} {status}", flush=True)

failures = [row for row in results if row["status"] == "FAIL"]
summary = {
    "case_count": len(results),
    "pass_count": len(results) - len(failures),
    "fail_count": len(failures),
    "results": results,
    "failures": failures,
}
output_path = Path(__file__).with_name("live-vs-excel-two-dimensions.json")
output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: summary[key] for key in ("case_count", "pass_count", "fail_count")}, ensure_ascii=False, indent=2))
print(f"FORMULA_COMPARISON_OUTPUT={output_path}")
raise SystemExit(1 if failures else 0)
