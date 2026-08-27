"""Read-only verification for the deployed shared-formula completion.

The script calls only /api/quotes/formula-template, compares all formula cells
listed in the migration, and evaluates the JE 500x500x180 single-door example
locally.  It never calls the quote calculation or confirmation endpoints.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.request


PATCH_PATTERN = re.compile(
    r"\('(?P<code>[A-Z_]+)',\s*(?P<row>\d+),\s*(?P<index>\d+),\s*"
    r"convert_from\(decode\('(?P<hex>[0-9a-f]+)', 'hex'\), 'UTF8'\),\s*"
    r"'(?P<cell>[A-Z]+\d+)'\)"
)


def parse_args():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--migration",
        type=Path,
        default=root / "database" / "migrations" / "complete_formula_shared_cells_from_workbooks.sql",
    )
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
        raise RuntimeError(f"HTTP {error.code} formula-template: {detail}") from error


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


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    base = api_base(config)
    key = str(config.get("api_key") or "").strip()
    migration = args.migration.read_text(encoding="utf-8")

    patches = defaultdict(list)
    for match in PATCH_PATTERN.finditer(migration):
        patches[match.group("code")].append({
            "row": int(match.group("row")),
            "index": int(match.group("index")),
            "formula": bytes.fromhex(match.group("hex")).decode("utf-8"),
            "cell": match.group("cell"),
        })
    patch_count = sum(map(len, patches.values()))
    if patch_count != 479:
        raise RuntimeError(f"migration patch count is {patch_count}, expected 479")

    payloads = {}
    mismatches = []
    verified_counts = {}
    for code in sorted(patches):
        payload = request_template(base, key, code)
        payloads[code] = payload
        rules = payload.get("template", {}).get("rules") or []
        rows = {
            int(rule.get("source_row_no") or (rule.get("raw_rule") or {}).get("source_row_no") or 0): rule
            for rule in rules
        }
        verified = 0
        for patch in patches[code]:
            rule = rows.get(patch["row"])
            formulas = list(((rule or {}).get("raw_rule") or {}).get("formulas") or [])
            actual = formulas[patch["index"]] if patch["index"] < len(formulas) else ""
            if actual != patch["formula"]:
                mismatches.append(f"{code}!{patch['cell']}")
            else:
                verified += 1
        verified_counts[code] = verified

    if mismatches:
        sample = ", ".join(mismatches[:20])
        raise RuntimeError(f"{len(mismatches)} formula cells still mismatch; first cells: {sample}")

    calculator = load_calculator(root)
    calculator.load_template(payloads["JE_SINGLE"])
    weight, area = calculator.calculate("JE_SINGLE", 500, 500, 180, 1, 0)
    if round(float(weight), 1) != 20.3 or round(float(area), 1) != 0.9:
        raise RuntimeError(f"JE verification failed: weight={weight}, area={area}")

    print("CLOUD_FORMULA_COMPLETION=PASS")
    print(json.dumps({
        "verified_formula_cells": patch_count,
        "by_template": verified_counts,
        "je_500x500x180_single": {
            "weight_kg": round(float(weight), 9),
            "area_m2": round(float(area), 9),
            "display_weight_kg": round(float(weight), 1),
            "display_area_m2": round(float(area), 1),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
