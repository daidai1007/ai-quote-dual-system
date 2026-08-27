from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop_client"))
os.environ.setdefault(
    "AI_QUOTE_V3_CORE_ROOT",
    r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core",
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

VERIFY_PATH = ROOT / "tests" / "verify_cloud_formula_door_matrix_readonly.py"
spec = importlib.util.spec_from_file_location("verify_formula", VERIFY_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

import v3_launcher


config_path = Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\client_config.json")
oracle_path = Path(__file__).with_name("excel-oracle-two-dimensions.json")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
base = module.api_base(config)
key = str(config.get("api_key") or "").strip()
namespace = v3_launcher.load_v3_namespace()
calculator = namespace["FormulaDatabaseCalculator"]()

template_codes = {
    code for codes in module.FAMILY_CODES.values() for code in codes.values()
} | set(module.SINGLE_CASE_CODES)
for code in sorted(template_codes):
    for attempt in range(4):
        try:
            payload = module.request_template(base, key, code)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)
    calculator.load_template(payload)

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
    status = "PASS" if math.isclose(weight_delta, 0, abs_tol=1e-8) and math.isclose(area_delta, 0, abs_tol=1e-8) else "FAIL"
    results.append({
        "dimension": expected["dimension"],
        "family": family,
        "doors": expected["doors"],
        "template_code": code,
        "runtime_weight_kg": weight,
        "excel_weight_kg": expected["weight_kg"],
        "weight_delta": weight_delta,
        "runtime_area_m2": area,
        "excel_area_m2": expected["area_m2"],
        "area_delta": area_delta,
        "status": status,
    })

failures = [row for row in results if row["status"] == "FAIL"]
summary = {
    "case_count": len(results),
    "pass_count": len(results) - len(failures),
    "fail_count": len(failures),
    "results": results,
    "failures": failures,
}
output_path = Path(__file__).with_name("v3-runtime-vs-excel-two-dimensions.json")
output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "case_count": summary["case_count"],
    "pass_count": summary["pass_count"],
    "fail_count": summary["fail_count"],
    "failures": failures,
}, ensure_ascii=False, indent=2))
print(f"V3_RUNTIME_COMPARISON_OUTPUT={output_path}")
raise SystemExit(1 if failures else 0)
