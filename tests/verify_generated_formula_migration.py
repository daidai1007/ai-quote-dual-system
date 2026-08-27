"""Evaluate the generated unified-door SQL payload with the real V3 engine."""

from __future__ import annotations

import ast
from collections import defaultdict
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "database" / "migrations" / "sync_unified_door_formula_templates.sql"
COMPLETION_SQL_PATH = ROOT / "database" / "migrations" / "complete_formula_shared_cells_from_workbooks.sql"
DOORS = ((1, 0), (0, 1), (0, 2), (2, 0), (1, 1))


def decoded_json(hex_text: str):
    return json.loads(bytes.fromhex(hex_text).decode("utf-8"))


sql = SQL_PATH.read_text(encoding="utf-8")
assert "part_name = COALESCE(d.part_name, '')" in sql
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

completion_sql = COMPLETION_SQL_PATH.read_text(encoding="utf-8")
completion_pattern = re.compile(
    r"\('(?P<code>[A-Z_]+)',\s*(?P<row>\d+),\s*(?P<index>\d+),\s*"
    r"convert_from\(decode\('(?P<hex>[0-9a-f]+)', 'hex'\), 'UTF8'\),\s*'(?P<cell>[A-Z]+\d+)'\)"
)
completion_patches = defaultdict(list)
for match in completion_pattern.finditer(completion_sql):
    completion_patches[match.group("code")].append({
        "source_row_no": int(match.group("row")),
        "formula_index": int(match.group("index")),
        "formula": bytes.fromhex(match.group("hex")).decode("utf-8"),
        "cell": match.group("cell"),
    })

assert sum(map(len, completion_patches.values())) == 479
for code, patches in completion_patches.items():
    if code not in rules:
        continue
    rows_by_number = {row["source_row_no"]: row for row in rules[code]}
    for patch in patches:
        row = rows_by_number[patch["source_row_no"]]
        formulas = row["raw_rule"].setdefault("formulas", [])
        formulas.extend([""] * (23 - len(formulas)))
        old_formula = formulas[patch["formula_index"]]
        assert old_formula in ("", patch["formula"]), (code, patch["cell"], old_formula)
        formulas[patch["formula_index"]] = patch["formula"]

expected_codes = {
    "JS_SINGLE", "JS_DOUBLE", "JP_SINGLE", "JP_DOUBLE",
    "JA_SINGLE", "JE_SINGLE", "JE_DOUBLE",
}
assert set(rules) == expected_codes, set(rules)
assert set(mappings) == expected_codes, set(mappings)

source = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(source)
calculator_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "FormulaDatabaseCalculator"
)
display_node = next(
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "formula_display_number"
)
calculator_module = ast.fix_missing_locations(ast.Module(body=[calculator_node], type_ignores=[]))
calculator_namespace = {"math": math, "re": re}
exec(compile(calculator_module, "FormulaDatabaseCalculator", "exec"), calculator_namespace)
calculator = calculator_namespace["FormulaDatabaseCalculator"]()
display_module = ast.fix_missing_locations(ast.Module(body=[display_node], type_ignores=[]))
display_namespace = {}
exec(compile(display_module, "formula_display_number", "exec"), display_namespace)
formula_display_number = display_namespace["formula_display_number"]
for code in sorted(expected_codes):
    calculator.load_template({
        "template": {
            "template_code": code,
            **mappings[code],
            "rules": sorted(rules[code], key=lambda row: row["source_row_no"]),
        }
    })

je_weight, je_area = calculator.calculate("JE_SINGLE", 500, 500, 180, 1, 0)
assert round(float(je_weight), 1) == 20.3, je_weight
assert round(float(je_area), 1) == 0.9, je_area

# Microsoft Excel CalculateFullRebuild oracle values from the authoritative
# JS/JP/JA/JE/JK/JM workbook. These cases protect both dimension order and the
# galvanized 2.0 mm installation-beam bucket that previously disappeared from
# the runtime total.
js_oracles = (
    ((800, 800, 800), (80.72750144609303, 8.557817499999016)),
    ((600, 2000, 600), (136.65249656609646, 14.081681499999501)),
    ((800, 300, 1800), (83.85487079608417, 10.357317499997762)),
)
for (width, height, depth), (expected_weight, expected_area) in js_oracles:
    actual_weight, actual_area = calculator.calculate(
        "JS_SINGLE", width, height, depth, 1, 0
    )
    assert math.isclose(actual_weight, expected_weight, rel_tol=0, abs_tol=1e-8), (
        width, height, depth, actual_weight, expected_weight
    )
    assert math.isclose(actual_area, expected_area, rel_tol=0, abs_tol=1e-8), (
        width, height, depth, actual_area, expected_area
    )

assert formula_display_number(js_oracles[0][1][0]) == "80.7"
assert formula_display_number(js_oracles[0][1][1]) == "8.6"
assert 'self.weight_edit.setText(formula_display_number(values[0]))' in source
assert 'self.area_edit.setText(formula_display_number(values[1]))' in source
assert 'f"{float(area):,.1f} m²"' in source

# Persist the Excel CalculateFullRebuild oracle for every migrated JS/JP/JA/JE
# door/template path at both requested regression dimensions.  JK and JM are
# verified against the deployed templates by the full V3 runtime audit because
# those two templates are not generated by this migration.
excel_oracle = (
    ('600x600x2000', 'JS_SINGLE', '1/0', 136.65249656609646, 14.081681499999501),
    ('600x600x2000', 'JS_SINGLE', '2/0', 286.1795370743964, 29.1337779999995),
    ('600x600x2000', 'JS_DOUBLE', '0/1', 138.50337080639648, 14.270433499999502),
    ('600x600x2000', 'JS_DOUBLE', '0/2', 300.6952093955964, 30.6437939999995),
    ('600x600x2000', 'JS_SINGLE', '1/1', 146.23804171499648, 14.2625299999995),
    ('600x600x2000', 'JP_SINGLE', '1/0', 82.63965311609647, 6.936453499999501),
    ('600x600x2000', 'JP_SINGLE', '2/0', 232.16669362439646, 21.9885499999995),
    ('600x600x2000', 'JP_DOUBLE', '0/1', 84.49052735639647, 7.125205499999501),
    ('600x600x2000', 'JP_DOUBLE', '0/2', 246.68236594559647, 23.4985659999995),
    ('600x600x2000', 'JP_SINGLE', '1/1', 92.22519826499648, 7.1173019999995),
    ('600x600x2000', 'JA_SINGLE', '1/0', 114.06182150039999, 5.76867276),
    ('600x600x2000', 'JA_SINGLE', '2/0', 140.0399237148, 7.02290652),
    ('600x600x2000', 'JA_SINGLE', '0/1', 115.12789947959999, 5.84829864),
    ('600x600x2000', 'JA_SINGLE', '0/2', 141.3039324732, 7.18215828),
    ('600x600x2000', 'JA_SINGLE', '1/1', 140.671928094, 7.1025324),
    ('600x600x2000', 'JE_SINGLE', '1/0', 114.67542720659999, 5.76867276),
    ('600x600x2000', 'JE_SINGLE', '2/0', 140.566714701, 7.02290652),
    ('600x600x2000', 'JE_DOUBLE', '0/1', 115.74150518580001, 5.84829864),
    ('600x600x2000', 'JE_DOUBLE', '0/2', 141.8307234594, 7.18215828),
    ('600x600x2000', 'JE_SINGLE', '1/1', 141.1987190802, 7.1025324),
    ('800x1800x300', 'JS_SINGLE', '1/0', 83.85487079608417, 10.357317499997762),
    ('800x1800x300', 'JS_SINGLE', '2/0', 113.70979327438415, 13.403113999997762),
    ('800x1800x300', 'JS_DOUBLE', '0/1', 84.20042903638416, 10.386269499997761),
    ('800x1800x300', 'JS_DOUBLE', '0/2', 116.18293759558416, 13.634729999997761),
    ('800x1800x300', 'JS_SINGLE', '1/1', 85.40471791498418, 10.382865999997762),
    ('800x1800x300', 'JP_SINGLE', '1/0', 66.22186010608418, 8.096353499997761),
    ('800x1800x300', 'JP_SINGLE', '2/0', 96.07678258438416, 11.142149999997763),
    ('800x1800x300', 'JP_DOUBLE', '0/1', 66.56741834638416, 8.125305499997763),
    ('800x1800x300', 'JP_DOUBLE', '0/2', 98.54992690558416, 11.373765999997762),
    ('800x1800x300', 'JP_SINGLE', '1/1', 67.77170722498417, 8.121901999997762),
    ('800x1800x300', 'JA_SINGLE', '1/0', 70.7295389004, 4.49607276),
    ('800x1800x300', 'JA_SINGLE', '2/0', 78.8733203148, 4.7576065199999995),
    ('800x1800x300', 'JA_SINGLE', '0/1', 70.3874210796, 4.508633639999999),
    ('800x1800x300', 'JA_SINGLE', '0/2', 77.0315550732, 4.78272828),
    ('800x1800x300', 'JA_SINGLE', '1/1', 77.952437694, 4.770167399999999),
    ('800x1800x300', 'JE_SINGLE', '1/0', 70.70361609659999, 4.49607276),
    ('800x1800x300', 'JE_SINGLE', '2/0', 78.76058279099999, 4.7576065199999995),
    ('800x1800x300', 'JE_DOUBLE', '0/1', 70.36149827579999, 4.508633639999999),
    ('800x1800x300', 'JE_DOUBLE', '0/2', 76.91881754939999, 4.78272828),
    ('800x1800x300', 'JE_SINGLE', '1/1', 77.8397001702, 4.770167399999999),
)
dimensions = {
    '600x600x2000': (600, 2000, 600),
    '800x1800x300': (800, 300, 1800),
}
for dimension, code, doors, expected_weight, expected_area in excel_oracle:
    single, double = (int(value) for value in doors.split('/'))
    actual_weight, actual_area = calculator.calculate(
        code, *dimensions[dimension], single, double
    )
    assert math.isclose(actual_weight, expected_weight, rel_tol=0, abs_tol=1e-8), (
        dimension, code, doors, actual_weight, expected_weight
    )
    assert math.isclose(actual_area, expected_area, rel_tol=0, abs_tol=1e-8), (
        dimension, code, doors, actual_area, expected_area
    )

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
