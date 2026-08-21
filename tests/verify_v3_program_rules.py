"""Offline contracts for the source-controlled V3 interaction overlay."""

from __future__ import annotations

import importlib.util
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
    "QFrame", "QHeaderView", "QHBoxLayout", "QMessageBox", "QPushButton",
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
assert 'cells[door_cells[0]] = int(single_door_count)' in source
assert 'cells[door_cells[1]] = int(double_door_count)' in source
assert 'DOOR_CONTROL_CELLS' in source

print("V3 program rule contracts passed")
