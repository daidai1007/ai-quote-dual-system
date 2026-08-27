from __future__ import annotations

import ast
from collections import defaultdict
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SQL_PATH = ROOT / "database" / "migrations" / "sync_unified_door_formula_templates.sql"
COMPLETION_SQL_PATH = ROOT / "database" / "migrations" / "complete_formula_shared_cells_from_workbooks.sql"


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

completion_sql = COMPLETION_SQL_PATH.read_text(encoding="utf-8")
completion_pattern = re.compile(
    r"\('(?P<code>[A-Z_]+)',\s*(?P<row>\d+),\s*(?P<index>\d+),\s*"
    r"convert_from\(decode\('(?P<hex>[0-9a-f]+)', 'hex'\), 'UTF8'\),\s*'(?P<cell>[A-Z]+\d+)'\)"
)
for match in completion_pattern.finditer(completion_sql):
    code = match.group("code")
    if code not in rules:
        continue
    source_row = int(match.group("row"))
    target = next(row for row in rules[code] if row["source_row_no"] == source_row)
    formulas = target["raw_rule"].setdefault("formulas", [])
    formulas.extend([""] * (23 - len(formulas)))
    formulas[int(match.group("index"))] = bytes.fromhex(match.group("hex")).decode("utf-8")

source = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(source)
calculator_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "FormulaDatabaseCalculator"
)
calculator_module = ast.fix_missing_locations(ast.Module(body=[calculator_node], type_ignores=[]))
namespace = {"math": math, "re": re}
exec(compile(calculator_module, "FormulaDatabaseCalculator", "exec"), namespace)
calculator = namespace["FormulaDatabaseCalculator"]()
for code in ("JS_SINGLE", "JS_DOUBLE"):
    calculator.load_template({"template": {"template_code": code, **mappings[code], "rules": rules[code]}})

result = calculator.calculate("JS_SINGLE", 800, 800, 800, 1, 0)
print(json.dumps({
    "result": result,
    "details": {
        str(row): {
            "name": values[0],
            "thickness": values[1],
            "weight": values[2],
            "treatment": values[3],
            "area": values[4],
        }
        for row, values in calculator.last_detail_values.items()
    },
}, ensure_ascii=False, indent=2))
