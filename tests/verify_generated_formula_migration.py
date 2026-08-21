"""Evaluate the generated unified-door SQL payload with the real V3 engine."""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "database" / "migrations" / "sync_unified_door_formula_templates.sql"
DOORS = ((1, 0), (0, 1), (0, 2), (2, 0), (1, 1))


def decoded_json(hex_text: str):
    return json.loads(bytes.fromhex(hex_text).decode("utf-8"))


sql = SQL_PATH.read_text(encoding="utf-8")
rule_pattern = re.compile(
    r"\('(?P<code>[A-Z_]+)',\s*(?P<ordinal>\d+),\s*(?P<row>\d+),\s*"
    r"convert_from\(decode\('(?P<hex>[0-9a-f]+)', 'hex'\), 'UTF8'\)::jsonb,\s*"
    r"(?P<material>TRUE|FALSE),\s*(?P<spray>TRUE|FALSE),"
)
mapping_pattern = re.compile(
    r"\('(?P<code>[A-Z_]+)',\s*'(?P<sheet>[^']+)',\s*"
    r"convert_from\(decode\('(?P<hex>[0-9a-f]+)', 'hex'\), 'UTF8'\)::jsonb,\s*"
    r"'(?P<weight>[A-Z]+\d+)',\s*'(?P<area>[A-Z]+\d+)'\)"
)

rules = defaultdict(list)
for match in rule_pattern.finditer(sql):
    rules[match.group("code")].append({
        "source_row_no": int(match.group("row")),
        "raw_rule": decoded_json(match.group("hex")),
        "include_material_cost": match.group("material") == "TRUE",
        "include_spray_area": match.group("spray") == "TRUE",
    })

mappings = {
    match.group("code"): {
        "source_sheet": match.group("sheet"),
        "option_cells": decoded_json(match.group("hex")),
        "weight_output_cell": match.group("weight"),
        "area_output_cell": match.group("area"),
    }
    for match in mapping_pattern.finditer(sql)
}

expected_codes = {
    "JS_SINGLE", "JS_DOUBLE", "JP_SINGLE", "JP_DOUBLE",
    "JA_SINGLE", "JE_SINGLE", "JE_DOUBLE",
}
assert set(rules) == expected_codes, set(rules)
assert set(mappings) == expected_codes, set(mappings)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "desktop_client"))
import v3_launcher  # noqa: E402

namespace = v3_launcher.load_v3_namespace()
calculator = namespace["FormulaDatabaseCalculator"]()
for code in sorted(expected_codes):
    calculator.load_template({
        "template": {
            "template_code": code,
            **mappings[code],
            "rules": sorted(rules[code], key=lambda row: row["source_row_no"]),
        }
    })

family_measurements = {}
for family in ("JS", "JP", "JA", "JE"):
    measurements = []
    for single, double in DOORS:
        if family == "JA":
            code = "JA_SINGLE"
        else:
            code = f"{family}_{'SINGLE' if single > 0 else 'DOUBLE'}"
        values = calculator.calculate(code, 600, 2000, 300, single, double)
        assert values and all(float(value) > 0 for value in values), (family, single, double, values)
        measurements.append(tuple(round(float(value), 6) for value in values))
    assert len(set(measurements)) == 5, (family, measurements)
    family_measurements[family] = measurements

print("UNIFIED_FORMULA_MIGRATION=PASS")
print(json.dumps(family_measurements, ensure_ascii=False))
