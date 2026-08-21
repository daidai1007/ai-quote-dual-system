"""Run the deployed 600x300x2000 quote matrix through the real V3 calculator.

This is an explicit cloud regression, not part of the offline ``npm verify``
suite.  It requires the packaged V3 core and a client configuration containing
the deployed API URL/key.  No credentials are printed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from uuid import uuid4


WIDTH_MM = 600.0
DEPTH_MM = 300.0
HEIGHT_MM = 2000.0
MODEL_CODE = "600×300×2000"
MULTI_DOOR_FAMILIES = ("JS", "JP", "JA", "JE")
MULTI_DOOR_COUNTS = ((1, 0), (0, 1), (0, 2), (2, 0), (1, 1))
OTHER_DOOR_COUNTS = ((1, 0), (0, 1))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-deployment", default="2026-08-21-unified-door-db-v3")
    return parser.parse_args()


def api_base(config: dict) -> str:
    url = str(config.get("api_url") or "").strip()
    if not url:
        raise RuntimeError("client config has no api_url")
    return url.split("/api/", 1)[0].rstrip("/")


def request_json(base: str, key: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {}
    if key:
        headers["X-AI-Quote-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(
        base + path,
        data=body,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {path}: {detail}") from error


def finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def family_for_code(code: str) -> str:
    upper = code.upper()
    for suffix in ("_SINGLE", "_DOUBLE"):
        if upper.endswith(suffix):
            return upper[: -len(suffix)]
    return upper


def multi_template_code(family: str, codes: set[str], single: int, double: int) -> str:
    if family == "JA":
        return "JA_SINGLE"
    wanted = f"{family}_{'SINGLE' if single > 0 else 'DOUBLE'}"
    if wanted in codes:
        return wanted
    fallback = f"{family}_SINGLE"
    if fallback in codes:
        return fallback
    raise RuntimeError(f"{family} has no usable formula template in the database catalogue")


def expected_surcharge(family: str, counts: tuple[int, int]) -> float:
    if counts == (0, 1):
        return 150.0 if family in {"JS", "JP"} else 60.0 if family in {"JA", "JE"} else 0.0
    if counts == (2, 0) and family in {"JS", "JP"}:
        return 150.0
    if counts == (0, 2) and family in {"JS", "JP"}:
        return 270.0
    return 0.0


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    base = api_base(config)
    key = str(config.get("api_key") or "").strip()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "desktop_client"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import v3_launcher  # noqa: E402

    namespace = v3_launcher.load_v3_namespace()
    calculator = namespace["FormulaDatabaseCalculator"]()

    health = request_json(base, key, "/health")
    database = request_json(base, key, "/api/health/database")
    catalog = request_json(base, key, "/api/products/catalog")
    if health.get("deployment") != args.expected_deployment:
        raise RuntimeError(
            f"deployment mismatch: {health.get('deployment')} != {args.expected_deployment}"
        )
    if database.get("ready") is not True:
        raise RuntimeError(f"database is not ready: {database}")

    items = [row for row in catalog.get("items") or [] if row.get("product_code")]
    codes = {str(row["product_code"]).upper() for row in items}
    materials = [row for row in catalog.get("materials") or [] if row.get("code")]
    material_code = "SECC" if any(row.get("code") == "SECC" for row in materials) else str(materials[0]["code"])
    coatings = [str(value) for value in catalog.get("coatings") or [] if str(value).strip()]
    coating_type = "橘纹" if "橘纹" in coatings else coatings[0]

    cases = []
    for family in MULTI_DOOR_FAMILIES:
        family_codes = {code for code in codes if family_for_code(code) == family}
        for counts in MULTI_DOOR_COUNTS:
            cases.append((family, multi_template_code(family, family_codes, *counts), counts, True))

    multi_codes = {code for code in codes if family_for_code(code) in MULTI_DOOR_FAMILIES}
    for code in sorted(codes - multi_codes):
        for counts in OTHER_DOOR_COUNTS:
            cases.append((family_for_code(code), code, counts, code in {"JK", "JM"}))

    results = []
    template_cache = {}
    for family, product_code, (single, double), formula_product in cases:
        result = {
            "family": family,
            "product_code": product_code,
            "doors": f"{single}/{double}",
            "status": "PASS",
            "errors": [],
        }
        weight = area = None
        try:
            if formula_product:
                template = template_cache.get(product_code)
                if template is None:
                    template = request_json(
                        base, key, "/api/quotes/formula-template", {"product_code": product_code}
                    )
                    template_cache[product_code] = template
                calculator.load_template(template)
                values = calculator.calculate(
                    product_code, WIDTH_MM, HEIGHT_MM, DEPTH_MM, single, double
                )
                if not values or not all(finite(value) and float(value) > 0 for value in values):
                    raise RuntimeError(f"invalid formula weight/area: {values}")
                weight, area = map(float, values)

            variant = "SINGLE" if single > 0 else "DOUBLE"
            payload = {
                "quote_id": f"REG-{uuid4().hex}",
                "product_code": product_code,
                "model_code": MODEL_CODE,
                "material_code": material_code,
                "width_mm": WIDTH_MM,
                "height_mm": HEIGHT_MM,
                "depth_mm": DEPTH_MM,
                "base_material_weight_kg": weight,
                "product_area_m2": area,
                "coating_type": coating_type,
                "variant_code": variant,
                "single_door_count": single,
                "double_door_count": double,
                "attachments": [],
            }
            quote = request_json(base, key, "/api/quotes/calculate-dual", payload)
            formula_total = (quote.get("formula_cost") or {}).get("total_cost")
            quick = quote.get("quick_quote") or {}
            quick_total = quick.get("total_cost")
            if not finite(formula_total):
                result["errors"].append(f"formula total missing: {formula_total}")
            if not finite(quick_total):
                result["errors"].append(f"quick total missing: {quick_total}")
            if family in MULTI_DOOR_FAMILIES:
                expected = expected_surcharge(family, (single, double))
                actual = (quote.get("door_variant_billing_rule") or {}).get("quick_price_surcharge")
                if not finite(actual) or float(actual) != expected:
                    result["errors"].append(f"quick surcharge {actual} != {expected}")
            result.update({
                "weight_kg": weight,
                "area_m2": area,
                "formula_total": formula_total,
                "quick_total": quick_total,
                "quick_base": quick.get("base_price"),
                "quick_match": quick.get("match_method"),
                "risk_flags": quote.get("risk_flags") or [],
            })
        except Exception as error:  # keep the full matrix running
            result["errors"].append(str(error))
        if result["errors"]:
            result["status"] = "FAIL"
        results.append(result)

    for family in MULTI_DOOR_FAMILIES:
        rows = [row for row in results if row["family"] == family and row["status"] == "PASS"]
        measurements = {
            (round(float(row["weight_kg"]), 6), round(float(row["area_m2"]), 6))
            for row in rows if row.get("weight_kg") is not None and row.get("area_m2") is not None
        }
        if len(rows) > 1 and len(measurements) != len(rows):
            for row in rows:
                row["status"] = "FAIL"
                row["errors"].append(
                    f"{family} produced only {len(measurements)} distinct weight/area pairs for {len(rows)} successful door combinations"
                )

    summary = {
        "specification": MODEL_CODE,
        "dimensions": {"width_mm": WIDTH_MM, "depth_mm": DEPTH_MM, "height_mm": HEIGHT_MM},
        "deployment": health.get("deployment"),
        "database_ready": database.get("ready"),
        "catalog_codes": sorted(codes),
        "case_count": len(results),
        "pass_count": sum(row["status"] == "PASS" for row in results),
        "fail_count": sum(row["status"] == "FAIL" for row in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["fail_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
