"""Offline contracts for the source-controlled V3 interaction overlay."""

from __future__ import annotations

import importlib.util
import ast
import math
import re
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Widget:
    pass


class DoubleSpin(Widget):
    def __init__(self, value=0):
        self._value = value
        self.special = None
        self.placeholder = None
        self.blocked = False

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def blockSignals(self, blocked):
        previous, self.blocked = self.blocked, blocked
        return previous

    def setSpecialValueText(self, value):
        self.special = value

    def lineEdit(self):
        return self

    def setPlaceholderText(self, value):
        self.placeholder = value

    def setAccessibleName(self, _value):
        pass

    def setToolTip(self, _value):
        pass


class Label(Widget):
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, value):
        self.text = value

    def setToolTip(self, value):
        self.tooltip = value


class LineEdit(Widget):
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class Combo(Widget):
    def __init__(self, value="JS"):
        self._value = value

    def currentData(self):
        return self._value


qt_core = types.ModuleType("PySide6.QtCore")
qt_core.QTimer = type("QTimer", (), {})
qt_core.Qt = type("Qt", (), {})
qt_widgets = types.ModuleType("PySide6.QtWidgets")
for name in (
    "QAbstractButton", "QCompleter", "QDialog", "QDialogButtonBox", "QFormLayout",
    "QFrame", "QGridLayout", "QHeaderView", "QHBoxLayout", "QMessageBox", "QPushButton",
    "QScrollArea", "QSizePolicy", "QSplitter", "QTableWidget", "QVBoxLayout", "QWidget",
):
    setattr(qt_widgets, name, type(name, (Widget,), {}))
qt_widgets.QComboBox = Combo
qt_widgets.QDoubleSpinBox = DoubleSpin
qt_widgets.QLabel = Label
qt_widgets.QLineEdit = LineEdit
pyside = types.ModuleType("PySide6")
sys.modules.update({"PySide6": pyside, "PySide6.QtCore": qt_core, "PySide6.QtWidgets": qt_widgets})

spec = importlib.util.spec_from_file_location("layout_refresh", ROOT / "desktop_client" / "layout_refresh.py")
layout_refresh = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(layout_refresh)

from attachment_category_browser import LEVEL1_ORDER, category_options  # noqa: E402
from quote_remark_rules import (  # noqa: E402
    DOOR_PHRASES_BY_COUNTS,
    replace_door_configuration_phrase,
)


assert LEVEL1_ORDER[:10] == (
    "底座", "侧板", "三排纵梁", "安装板", "灯开关", "文件夹", "风机滤网",
    "门限位器", "门加强筋", "配置变形",
)
mixed_options = category_options(
    [
        {"category_level1": "安装板", "category_level2": "JK安装板"},
        {"category_level1": "安装板", "category_level2": ""},
    ],
    ["安装板"],
)
assert mixed_options == [
    {"value": "JK安装板", "label": "JK安装板", "count": 1},
    {"value": "", "label": "本级附件", "count": 1},
]
assert DOOR_PHRASES_BY_COUNTS == {
    (1, 0): "前单开门",
    (0, 1): "前双开门",
    (2, 0): "前后单开门",
    (0, 2): "前后双开门",
    (1, 1): "前单开门后双开门",
}
for counts, expected in DOOR_PHRASES_BY_COUNTS.items():
    original = "手工录入，碳钢喷塑RAL7035橘纹，前双开门后背板，配风机1个。"
    actual = replace_door_configuration_phrase(
        original,
        {"single_door_count": counts[0], "double_door_count": counts[1]},
    )
    assert actual == original.replace("前双开门后背板", expected)
assert replace_door_configuration_phrase(
    "手工录入，碳钢喷塑RAL7035橘纹，配风机1个。",
    {"single_door_count": 1, "double_door_count": 0},
) == "手工录入，碳钢喷塑RAL7035橘纹，配风机1个。"


assert layout_refresh.VALID_DOOR_COMBINATIONS == {(1, 0), (0, 1), (0, 2), (2, 0), (1, 1)}
assert layout_refresh._parse_specification_dimensions("1000*600*1800") == (1000, 1800, 600)
assert layout_refresh._parse_specification_dimensions("1000×600×1800") == (1000, 1800, 600)
assert layout_refresh._parse_specification_dimensions("1000-600-1800") is None


class ManualWindow:
    def __init__(self):
        self.active_drawing = None
        self.width_spin = DoubleSpin()
        self.height_spin = DoubleSpin()
        self.depth_spin = DoubleSpin()
        self.quote_parameter_source = Label()
        self.calls = []

    def clear_quote_result(self):
        self.calls.append("clear")

    def refresh_formula_inputs(self):
        self.calls.append("formula")

    def request_history_match(self):
        self.calls.append("history")

    def update_quote_readiness(self):
        self.calls.append("ready")


manual = ManualWindow()
assert layout_refresh._sync_manual_specification_to_dimensions(manual, "1200*500*1600")
assert (manual.width_spin.value(), manual.depth_spin.value(), manual.height_spin.value()) == (1200, 500, 1600)
assert manual.quote_parameter_source.text == "来源：人工输入规格"
assert manual.calls == ["clear", "formula", "history", "ready"]
manual.active_drawing = {"name": "drawing.pdf"}
assert not layout_refresh._sync_manual_specification_to_dimensions(manual, "900*400*1400")
assert manual.width_spin.value() == 1200


class Calculator:
    def calculate(self, code, width, height, depth, single, double):
        assert (code, width, height, depth, single, double) == ("JS_SINGLE", 1000, 1800, 600, 1, 0)
        return 100, 20


class FormulaWindow:
    product_combo = Combo("JS")
    product_catalog = {
        "JS": {
            "method": "formula",
            "defaults": (1000, 1800, 600),
            "defaults_by_variant": {"SINGLE": (1000, 1800, 600)},
        }
    }
    width_spin = DoubleSpin(1200)
    height_spin = DoubleSpin(1800)
    depth_spin = DoubleSpin(600)
    formula_calculator = Calculator()
    weight_edit = LineEdit()
    area_edit = LineEdit()
    quote_parameter_source = Label()

    @staticmethod
    def selected_variant_code():
        return "SINGLE"

    @staticmethod
    def selected_product_code():
        return "JS_SINGLE"

    @staticmethod
    def door_counts():
        return 1, 0


formula = FormulaWindow()
assert layout_refresh._apply_nonstandard_formula_ratio(formula)
expected_ratio = (1200 + 1800 + 600) / (1000 + 1800 + 600)
assert abs(float(formula.weight_edit.value) - 100 * expected_ratio) < 1e-6
assert abs(float(formula.area_edit.value) - 20 * expected_ratio) < 1e-6
assert abs(formula._nonstandard_perimeter_ratio - expected_ratio) < 1e-12


source = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(source)
calculator_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "FormulaDatabaseCalculator"
)
calculator_module = ast.fix_missing_locations(ast.Module(body=[calculator_node], type_ignores=[]))
calculator_namespace = {"math": math, "re": re}
exec(compile(calculator_module, "FormulaDatabaseCalculator", "exec"), calculator_namespace)
formula_calculator = calculator_namespace["FormulaDatabaseCalculator"]()
assert formula_calculator.DETAIL_ROWS["JP_SINGLE"][:3] == (5, 26, 29)
door_combinations = ((1, 0), (0, 1), (0, 2), (2, 0), (1, 1))
expected_weights = (10, 20, 40, 20, 30)
for product_code in ("JS_SINGLE", "JP_SINGLE", "JA_SINGLE", "JE_SINGLE"):
    single_cell, double_cell = formula_calculator.DOOR_CONTROL_CELLS[product_code]
    formula_calculator.sheets = {
        product_code: {
            "cells": {"E5": "后背板", "H5": 1, "N5": ""},
            "formulas": {
                "M5": f"{single_cell}*10+{double_cell}*20",
                "Y5": f"{single_cell}*2+{double_cell}*3",
            },
        }
    }
    area_divisor = formula_calculator.DETAIL_ROWS[product_code][4]
    for counts, expected_weight in zip(door_combinations, expected_weights):
        weight, area = formula_calculator.calculate(product_code, 1000, 1800, 600, *counts)
        assert weight == expected_weight, (product_code, counts, weight)
        assert area == (counts[0] * 2 + counts[1] * 3) / area_divisor

# Quoted model names that resemble Excel addresses must remain text.  The JE
# template uses MS828 in lock-rod branches; treating it as a cell reference
# drops the lock-rod weight or makes the strict V3 evaluator reject the row.
formula_calculator.sheets = {
    "JE_SINGLE": {
        "cells": {"H5": 7, "M5": 12, "N5": "", "Y5": 1},
        "formulas": {"E5": 'IF(B16=1,"MS828锁杆","")'},
    }
}
weight, area = formula_calculator.calculate("JE_SINGLE", 600, 2000, 300, 1, 0)
assert weight == 12, weight
assert area == 0.5, area


class DoorRuleWindow:
    def __init__(self, family, codes, counts):
        self.product_combo = Combo(family)
        self.product_catalog = {family: {"codes": codes}}
        self._counts = counts
        self.refreshed = 0

    def door_counts(self):
        return self._counts

    def set_door_counts(self, single, double):
        self._counts = (single, double)

    def refresh_formula_inputs(self):
        self.refreshed += 1

    def request_history_match(self):
        self.refreshed += 1


ja_window = DoorRuleWindow("JA", {"SINGLE": "JA_SINGLE"}, (0, 2))
assert layout_refresh._allowed_door_combinations(ja_window) == layout_refresh.VALID_DOOR_COMBINATIONS
assert not layout_refresh._enforce_product_door_combination(ja_window, "double")
other_window = DoorRuleWindow("XX", {"SINGLE": "XX_SINGLE", "DOUBLE": "XX_DOUBLE"}, (1, 1))
assert layout_refresh._allowed_door_combinations(other_window) == {(1, 0), (0, 1)}
assert layout_refresh._enforce_product_door_combination(other_window, "double")
assert other_window.door_counts() == (0, 1)
assert other_window.refreshed == 2

print("V3 program rule contracts passed")
