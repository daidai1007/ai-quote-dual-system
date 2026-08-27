"""Compare deployed formula templates with a Microsoft Excel oracle matrix."""

from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.request


DOOR_COMBINATIONS = ((1, 0), (2, 0), (0, 1), (0, 2), (1, 1))
FAMILY_CODES = {
    "JS": {"SINGLE": "JS_SINGLE", "DOUBLE": "JS_DOUBLE"},
    "JP": {"SINGLE": "JP_SINGLE", "DOUBLE": "JP_DOUBLE"},
    "JA": {"SINGLE": "JA_SINGLE"},
    "JE": {"SINGLE": "JE_SINGLE", "DOUBLE": "JE_DOUBLE"},
}
SINGLE_CASE_CODES = ("JK", "JM")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--width", type=float, default=200)
    parser.add_argument("--height", type=float, default=200)
    parser.add_argument("--depth", type=float, default=200)
    parser.add_argument(
        "--oracle",
        type=Path,
        default=Path(".codex-tmp/spreadsheet-audit/excel-formula-matrix-200.json"),
    )
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def api_base(config: dict) -> str:
    url = str(config.get("api_url") or "").strip()
    if not url:
        raise RuntimeError("client config has no api_url")
    return url.split("/api/", 1)[0].rstrip("/")


def request_template(base: str, key: str, product_code: str) -> dict:
    body = json.dumps({"product_code": product_code}).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if key:
        headers["X-AI-Quote-Key"] = key
    request = urllib.request.Request(
        base + "/api/quotes/formula-template",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {product_code}: {detail}") from error


def load_calculator(root: Path):
    source = (root / "desktop_client" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calculator_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FormulaDatabaseCalculator"
    )
    module = ast.fix_missing_locations(ast.Module(body=[calculator_node], type_ignores=[]))
    namespace = {"math": math, "re": re}
    exec(compile(module, "FormulaDatabaseCalculator", "exec"), namespace)
    return namespace["FormulaDatabaseCalculator"]()


def selected_template(codes: dict[str, str], single: int, double: int) -> str:
    if single > 0 and "SINGLE" in codes:
        return codes["SINGLE"]
    if double > 0 and "DOUBLE" in codes:
        return codes["DOUBLE"]
    if "SINGLE" in codes:
        return codes["SINGLE"]
    return codes["DOUBLE"]


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    base = api_base(config)
    key = str(config.get("api_key") or "").strip()
    calculator = load_calculator(root)
    oracle_payload = json.loads(args.oracle.read_text(encoding="utf-8-sig"))
    oracle_dimensions = oracle_payload.get("dimensions_mm") or {}
    expected_dimensions = {
        "width": args.width,
        "depth": args.depth,
        "height": args.height,
    }
    if any(
        float(oracle_dimensions.get(key, float("nan"))) != float(value)
        for key, value in expected_dimensions.items()
    ):
        raise RuntimeError(
            f"oracle dimensions {oracle_dimensions} do not match {expected_dimensions}"
        )
    oracle = {
        (str(row["family"]), str(row["doors"])): row
        for row in oracle_payload.get("results") or []
    }

    templates = {}
    template_codes = {
        code for codes in FAMILY_CODES.values() for code in codes.values()
    } | set(SINGLE_CASE_CODES)
    for code in sorted(template_codes):
        templates[code] = request_template(base, key, code)
        calculator.load_template(templates[code])

    results = []
    failures = []
    cases = [
        (family, codes, single, double, f"{single}/{double}")
        for family, codes in FAMILY_CODES.items()
        for single, double in DOOR_COMBINATIONS
    ] + [
        (code, {"SINGLE": code}, 1, 0, "-") for code in SINGLE_CASE_CODES
    ]
    for family, codes, single, double, door_label in cases:
        template_code = selected_template(codes, single, double)
        values = calculator.calculate(
            template_code,
            args.width,
            args.height,
            args.depth,
            single,
            double,
        )
        status = "PASS"
        errors = []
        oracle_row = oracle.get((family, door_label))
        if oracle_row is None:
            errors.append("Excel oracle row is missing")
            expected_weight = expected_area = None
        else:
            expected_weight = float(oracle_row["weight_kg"])
            expected_area = float(oracle_row["area_m2"])
            if template_code != oracle_row.get("template_code"):
                errors.append(
                    "template mismatch: "
                    f"{template_code} != {oracle_row.get('template_code')}"
                )
        if not values:
            errors.append("calculator returned no result")
            weight = area = None
        else:
            weight, area = map(float, values)
            if not math.isfinite(weight) or weight <= 0:
                errors.append(f"non-positive or invalid weight: {weight}")
            if not math.isfinite(area) or area <= 0:
                errors.append(f"non-positive or invalid area: {area}")
            if expected_weight is not None and not math.isclose(
                weight, expected_weight, rel_tol=0, abs_tol=args.tolerance
            ):
                errors.append(
                    f"weight differs from Excel: {weight} != {expected_weight}"
                )
            if expected_area is not None and not math.isclose(
                area, expected_area, rel_tol=0, abs_tol=args.tolerance
            ):
                errors.append(
                    f"area differs from Excel: {area} != {expected_area}"
                )
        if errors:
            status = "FAIL"
            failures.append(f"{family} {door_label}: {'; '.join(errors)}")
        results.append({
            "family": family,
            "doors": door_label,
            "template_code": template_code,
            "weight_kg": None if weight is None else round(weight, 9),
            "area_m2": None if area is None else round(area, 9),
            "excel_weight_kg": expected_weight,
            "excel_area_m2": expected_area,
            "weight_delta": None if weight is None or expected_weight is None else weight - expected_weight,
            "area_delta": None if area is None or expected_area is None else area - expected_area,
            "display_weight_kg": None if weight is None else round(weight, 1),
            "display_area_m2": None if area is None else round(area, 1),
            "status": status,
            "errors": errors,
        })

    summary = {
        "mode": "read-only deployed formula-template vs Microsoft Excel oracle",
        "dimensions_mm": {"width": args.width, "depth": args.depth, "height": args.height},
        "case_count": len(results),
        "pass_count": sum(row["status"] == "PASS" for row in results),
        "fail_count": len(failures),
        "tolerance": args.tolerance,
        "results": results,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if failures:
        print("FORMULA_DOOR_MATRIX=FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("FORMULA_DOOR_MATRIX=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
