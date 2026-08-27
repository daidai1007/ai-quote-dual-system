from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import urllib.request


CODE = sys.argv[1]
ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_DIR))
os.environ["AI_QUOTE_V3_CORE_ROOT"] = str(
    Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core")
)
from v3_launcher import load_v3_namespace  # noqa: E402


def selected_code(family: str, single: int, double: int) -> str:
    if family in ("JK", "JM"):
        return family
    if family == "JA":
        return "JA_SINGLE"
    return f"{family}_{'SINGLE' if single > 0 else 'DOUBLE'}"


config = json.loads(
    Path(r"G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\client_config.json").read_text(encoding="utf-8-sig")
)
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
    data=json.dumps({"product_code": CODE}).encode("utf-8"), headers=headers, method="POST",
)
with urllib.request.urlopen(request, timeout=90) as response:
    payload = json.loads(response.read().decode("utf-8"))

namespace = load_v3_namespace()
calculator = namespace["FormulaDatabaseCalculator"]()
calculator.load_template(payload)
oracle = json.loads(Path(__file__).with_name("excel-oracle-two-dimensions.json").read_text(encoding="utf-8-sig"))["results"]
rows = []
for expected in oracle:
    single, double = (1, 0) if expected["doors"] == "-" else tuple(map(int, expected["doors"].split("/")))
    if selected_code(expected["family"], single, double) != CODE:
        continue
    weight, area = calculator.calculate(
        CODE, expected["width_mm"], expected["height_mm"], expected["depth_mm"], single, double,
    )
    pass_value = math.isclose(float(weight), float(expected["weight_kg"]), abs_tol=1e-8) and math.isclose(float(area), float(expected["area_m2"]), abs_tol=1e-8)
    rows.append({"dimension": expected["dimension"], "family": expected["family"], "doors": expected["doors"], "pass": pass_value, "weight_delta": float(weight) - float(expected["weight_kg"]), "area_delta": float(area) - float(expected["area_m2"])})
print(json.dumps({"runtime": "v3_launcher/main.raw + layout_refresh", "template_code": CODE, "case_count": len(rows), "pass_count": sum(row["pass"] for row in rows), "failures": [row for row in rows if not row["pass"]]}, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(row["pass"] for row in rows) else 1)
