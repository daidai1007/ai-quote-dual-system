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
CLIENT_ROOT = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_ROOT))


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


class Thread(Widget):
    def __init__(self, *args, **kwargs):
        pass


class SignalStub:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, *_args, **_kwargs):
        pass

    def emit(self, *_args, **_kwargs):
        pass


qt_core = types.ModuleType("PySide6.QtCore")
qt_core.QPoint = type("QPoint", (), {})
qt_core.QTimer = type("QTimer", (), {})
qt_core.Qt = type("Qt", (), {})
qt_core.QThread = Thread
qt_core.Signal = SignalStub
qt_widgets = types.ModuleType("PySide6.QtWidgets")
for name in (
    "QAbstractButton", "QCompleter", "QDialog", "QDialogButtonBox", "QFormLayout",
    "QFrame", "QGridLayout", "QHeaderView", "QHBoxLayout", "QMessageBox", "QPushButton",
    "QScrollArea", "QSizePolicy", "QSplitter", "QTableWidget", "QTableWidgetItem", "QVBoxLayout", "QWidget",
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

from attachment_category_browser import (  # noqa: E402
    DEFAULT_A4_FOLDER,
    DEFAULT_DOOR_REINFORCEMENT,
    DEFAULT_DOOR_LIMITER,
    DEFAULT_GROUND_WIRE,
    DEFAULT_JP_SIDE_PANEL,
    DEFAULT_LIGHT_SWITCH,
    DOOR_LIMITER_DEFAULT_QUANTITIES,
    DOOR_TRANSFORMATION_RULE_PREFIX,
    LEVEL1_ORDER,
    category_options,
    default_rule_for_item,
    door_limiter_default_quantity,
    door_reinforcement_default_quantity,
    door_transformation_default_names,
    final_attachment_quantity,
    is_jp_product,
    match_default_a4_folder,
    match_default_door_reinforcement,
    match_default_door_limiter,
    match_default_ground_wire,
    match_default_light_switch,
    match_door_transformation_defaults,
    match_fixed_base,
    match_jp_side_panel,
    parse_base_specification,
)
from quote_remark_rules import (  # noqa: E402
    DOOR_PHRASES_BY_COUNTS,
    replace_door_configuration_phrase,
)
from ganged_cabinet_rules import (  # noqa: E402
    cascade_door_counts,
    ganged_split_count,
    parse_ganged_specification,
    subcabinet_specification,
)
from quick_discount_rules import (  # noqa: E402
    quick_order_line_breakdown,
    quick_discount_breakdown,
    quick_discount_category,
)


assert LEVEL1_ORDER[:11] == (
    "底座", "侧板", "三排纵梁", "安装板", "灯开关", "文件夹", "风机滤网",
    "门限位器", "门加强筋", "配置变形", "门变形",
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

expected_door_transformations = {
    ("JS", 1, 0): (),
    ("JS", 2, 0): ("JS、JP后背板改为单开门",),
    ("JP", 0, 1): ("JS、JP单开门改为双开门",),
    ("JS", 0, 2): ("JS、JP单开门改为双开门", "JS、JP后背板改为双开门"),
    ("JP", 1, 1): ("JS、JP后背板改为双开门",),
    ("JA", 1, 0): (),
    ("JA", 0, 1): ("JA、JE单开门改为双开门",),
    ("JE", 0, 2): (),
    ("JE", 2, 0): (),
    ("JE", 1, 1): (),
}
for (family, single, double), expected in expected_door_transformations.items():
    assert door_transformation_default_names(family, single, double) == expected

door_catalog = [
    {"attachment_price_id": 9, "category_level1": "门变形", "item_name": "JS、JP后背板改为双开门"},
    {"attachment_price_id": 3, "category_level1": "门变形", "item_name": "JS、JP单开门改为双开门"},
    {"attachment_price_id": 2, "category_level1": "门变形", "item_name": "JS、JP单开门改为双开门"},
]
door_matches = match_door_transformation_defaults(door_catalog, "JS_SINGLE", 0, 2)
assert set(door_matches) == {
    DOOR_TRANSFORMATION_RULE_PREFIX + "JS、JP单开门改为双开门",
    DOOR_TRANSFORMATION_RULE_PREFIX + "JS、JP后背板改为双开门",
}
assert door_matches[DOOR_TRANSFORMATION_RULE_PREFIX + "JS、JP单开门改为双开门"]["attachment_price_id"] == 2

for attachment, cabinets, expected in (
    ({"item_name": "安装板", "quantity": 2}, 3, 6),
    ({"item_name": "侧板", "quantity": 2}, 3, 2),
    ({"category_level1": "门变形", "item_name": "JS、JP后背板改为单开门", "quantity": 1}, 3, 1),
    ({"item_name": "KA2206风机", "quantity": 2}, 3, 2),
    ({"item_name": "FU滤网", "quantity": 2}, 3, 2),
):
    assert final_attachment_quantity(attachment, cabinets) == expected

assert final_attachment_quantity({"item_name": "安装板", "quantity": 2}, 3, 4) == 24
assert final_attachment_quantity({"item_name": "侧板", "quantity": 2}, 3, 4) == 2
assert final_attachment_quantity(
    {"category_level1": "门变形", "item_name": "JS、JP单开门改为双开门", "quantity": 1},
    3,
    4,
) == 1
assert final_attachment_quantity({"item_name": "FU滤网", "quantity": 2}, 3, 4) == 2
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
assert DOOR_LIMITER_DEFAULT_QUANTITIES == {
    (1, 0): 1,
    (2, 0): 2,
    (0, 1): 2,
    (0, 2): 4,
    (1, 1): 3,
}
for counts, quantity in DOOR_LIMITER_DEFAULT_QUANTITIES.items():
    assert door_limiter_default_quantity(*counts) == quantity
    assert door_reinforcement_default_quantity(*counts) == quantity
assert door_limiter_default_quantity(0, 0) is None
assert door_limiter_default_quantity("invalid", 1) is None
assert layout_refresh._parse_specification_dimensions("1000*600*1800") == (1000, 1800, 600)
assert layout_refresh._parse_specification_dimensions("1000×600×1800") == (1000, 1800, 600)
assert layout_refresh._parse_specification_dimensions("760*500*(960+100)") == (760, 960, 500)
assert layout_refresh._parse_specification_dimensions("1000-600-1800") is None
assert parse_base_specification("760*500*(960+100)") == (760, 960, 500, 100)
assert parse_base_specification("760×500×（960＋200）") == (760, 960, 500, 200)
assert parse_base_specification("760*500*960") is None
assert parse_base_specification("760*500*960+100") is None

ganged = parse_ganged_specification("（200+200）×600×（600+200）")
assert ganged is not None
assert ganged["split_count"] == 2
assert ganged["rows"] == [
    {"width_mm": 200.0, "depth_mm": 600.0, "height_mm": 600.0, "base_height_mm": 200.0},
    {"width_mm": 200.0, "depth_mm": 600.0, "height_mm": 600.0, "base_height_mm": 200.0},
]
assert subcabinet_specification(ganged["rows"][0]) == "200×600×（600+200）"
assert parse_base_specification("（200+200）×600×（600+200）") == (200, 600, 600, 200)
assert parse_base_specification("(200+200)/600/(600+200)") == (200, 600, 600, 200)
assert parse_ganged_specification("(200+300+400)×600×800")["split_count"] == 3
for separator in ("×", "x", "X", "*", "/"):
    compatible = parse_ganged_specification(
        f"(200+300){separator}600{separator}(800+100)"
    )
    assert compatible is not None
    assert compatible["widths_mm"] == [200, 300]
    assert compatible["depth_mm"] == 600
    assert compatible["height_mm"] == 800
    assert compatible["base_height_mm"] == 100
assert parse_ganged_specification("(200+300)x600/(800+100)")["split_count"] == 2
assert parse_ganged_specification("200×600×600") is None
assert parse_ganged_specification("(200＋200)×600×600") is None
door_rows = [
    {"single_door_count": 1, "double_door_count": 0},
    {"single_door_count": 1, "double_door_count": 0},
    {"single_door_count": 1, "double_door_count": 0},
]
door_rows = cascade_door_counts(door_rows, 1, 0, 2)
assert [(row["single_door_count"], row["double_door_count"]) for row in door_rows] == [
    (1, 0), (0, 2), (0, 2),
]
assert ganged_split_count({"ganged_cabinets": door_rows}) == 3
base_catalog = [
    {
        "attachment_price_id": 1,
        "item_name": "固定底座",
        "category_level1": "底座",
        "category_level2": "固定底座",
        "width_mm": 760,
        "height_mm": 100,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 2,
        "item_name": "活动底座",
        "category_level1": "底座",
        "category_level2": "活动底座",
        "width_mm": 760,
        "height_mm": 100,
        "depth_mm": 500,
    },
]
assert match_fixed_base(base_catalog, 760, 500, 100)["attachment_price_id"] == 1
assert match_fixed_base(base_catalog, 760, 500, 200) is None
default_catalog = [
    {"attachment_price_id": 3, "item_name": "照明灯/行程开关", "category_level1": "灯开关"},
    {"attachment_price_id": 4, "item_name": "A3资料盒", "category_level1": "文件夹"},
    {"attachment_price_id": 5, "item_name": "A4资料盒", "category_level1": "文件夹"},
    {"attachment_price_id": 6, "item_name": "门限位器", "category_level1": "门限位器"},
    {"attachment_price_id": 9, "item_name": "门加强筋", "category_level1": "门加强筋"},
    {"attachment_price_id": 10, "item_name": "接地线", "model_code": "红绿线", "category_level1": "接地线", "category_level2": "红绿线"},
    {"attachment_price_id": 11, "item_name": "接地线", "model_code": "编织带", "category_level1": "接地线", "category_level2": "编织带"},
    {"attachment_price_id": 7, "item_name": "侧板", "model_code": "JP681960", "category_level1": "侧板", "height_mm": 1900, "depth_mm": 600},
    {"attachment_price_id": 8, "item_name": "侧板", "model_code": "JP682060", "category_level1": "侧板", "height_mm": 2000, "depth_mm": 600},
]
assert match_default_light_switch(default_catalog)["attachment_price_id"] == 3
assert match_default_a4_folder(default_catalog)["attachment_price_id"] == 5
assert match_default_door_limiter(default_catalog)["attachment_price_id"] == 6
assert match_default_door_reinforcement(default_catalog)["attachment_price_id"] == 9
assert match_default_ground_wire(default_catalog)["attachment_price_id"] == 10
assert match_jp_side_panel(default_catalog, 2000, 600)["attachment_price_id"] == 8
assert match_jp_side_panel(default_catalog, 2000, 800) is None
assert is_jp_product("JP") and is_jp_product("JP_SINGLE") and not is_jp_product("JS_SINGLE")
assert default_rule_for_item({"item_name": "A4资料盒"}) == DEFAULT_A4_FOLDER
assert default_rule_for_item({"item_name": "门限位器"}) == DEFAULT_DOOR_LIMITER
assert default_rule_for_item({"item_name": "门加强筋"}) == DEFAULT_DOOR_REINFORCEMENT
assert default_rule_for_item({"item_name": "接地线", "model_code": "红绿线"}) == DEFAULT_GROUND_WIRE
assert default_rule_for_item({"item_name": "照明灯/行程开关"}) == DEFAULT_LIGHT_SWITCH
assert default_rule_for_item({"item_name": "侧板", "model_code": "JP682060"}) == DEFAULT_JP_SIDE_PANEL


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
            "cells": {"E5": "后背板", "H5": 2, "N5": ""},
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

# Weight buckets must follow each source workbook instead of using a single
# cross-family thickness list.  JE includes 2.0 mm galvanized sheet; JP alone
# includes ordinary 1.0 mm and 1.5 mm frame rows.
for product_code, cells, expected_weight in (
    ("JE_SINGLE", {"E5": "绑线条", "H5": 2, "M5": 6.25, "N5": "镀锌板", "Y5": 0}, 6.25),
    ("JS_SINGLE", {"E5": "普通板", "H5": 1, "M5": 8, "N5": "", "Y5": 0}, 0),
    ("JP_SINGLE", {"E5": "普通板", "H5": 1, "M5": 8, "N5": "", "Y5": 0}, 8),
    ("JP_SINGLE", {"E5": "框架", "H5": 1.5, "M5": 9, "N5": "", "Y5": 0}, 9),
):
    formula_calculator.sheets = {product_code: {"cells": cells, "formulas": {}}}
    weight, _area = formula_calculator.calculate(product_code, 500, 500, 180, 1, 0)
    assert weight == expected_weight, (product_code, cells, weight)

# Excel does not interpret its imported chained comparison as Python's range
# syntax.  At depth 200 the real JS workbook returns K5=1, not K5=2.
formula_calculator.sheets = {
    "JS_SINGLE": {
        "cells": {
            "E5": "左右侧板_1", "H5": 1.5, "I5": 0.000001,
            "J5": 7.85, "N5": "", "B14": 1.5,
        },
        "formulas": {
            "F5": "B7+53-2.5",
            "G5": "B8+64",
            "K5": 'IF(AND(B14=1.5,1000>=B8>=350,B7<1000),"1","2")',
            "L5": "K5*B9",
            "M5": "L5*J5*I5*H5*G5*F5*1.2",
            "Y5": "(F5/1000)*(G5/1000)*2*L5",
        },
    }
}
weight, area = formula_calculator.calculate("JS_SINGLE", 200, 200, 200, 1, 0)
assert abs(weight - 0.93444516) < 1e-9, weight
assert abs(area - 0.132264) < 1e-9, area

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


class DoorLimiterWindow:
    def __init__(self):
        self._counts = (1, 0)
        self._attachment_default_door_counts = (1, 0)
        self.attachment_default_opt_outs = set()
        self.attachment_default_quantity_overrides = set()
        self.attachments = [
            {"item_name": "门限位器", "category_level1": "门限位器", "quantity": 1},
            {"item_name": "门加强筋", "category_level1": "门加强筋", "quantity": 1},
            {"item_name": "A4资料盒", "category_level1": "文件夹", "quantity": 9},
        ]
        self.view_refreshes = 0

    def door_counts(self):
        return self._counts

    def update_attachment_view(self):
        self.view_refreshes += 1


limiter_window = DoorLimiterWindow()
limiter_window._counts = (0, 2)
assert layout_refresh._sync_door_limiter_default_quantity(limiter_window, (1, 0))
assert limiter_window.attachments[0]["quantity"] == 4
assert limiter_window.attachments[1]["quantity"] == 4
assert limiter_window.attachments[2]["quantity"] == 9
assert limiter_window.view_refreshes == 1
assert not layout_refresh._sync_door_limiter_default_quantity(limiter_window, (0, 2))

limiter_window.attachment_default_quantity_overrides = {
    DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT,
}
limiter_window.attachments[0]["quantity"] = 7
limiter_window.attachments[1]["quantity"] = 8
limiter_window._counts = (1, 1)
assert not layout_refresh._sync_door_limiter_default_quantity(limiter_window, (0, 2))
assert limiter_window.attachments[0]["quantity"] == 7
assert limiter_window.attachments[1]["quantity"] == 8

limiter_window.attachment_default_quantity_overrides.clear()
limiter_window.attachment_default_opt_outs = {
    DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT,
}
limiter_window.attachments = [limiter_window.attachments[2]]
limiter_window._counts = (2, 0)
assert not layout_refresh._sync_door_limiter_default_quantity(limiter_window, (1, 1))
assert all(item.get("item_name") != "门限位器" for item in limiter_window.attachments)
assert all(item.get("item_name") != "门加强筋" for item in limiter_window.attachments)


class DoorTransformWindow:
    def __init__(self):
        self._counts = (1, 0)
        self._product = "JS_SINGLE"
        self.attachment_door_transform_context = ("JS_SINGLE", (1, 0))
        self.attachment_default_opt_outs = {
            DOOR_TRANSFORMATION_RULE_PREFIX + "JS、JP后背板改为单开门",
        }
        self.attachments = [{"item_name": "侧板", "category_level1": "侧板", "quantity": 2}]
        self.attachment_door_transform_catalog = [
            {"attachment_price_id": 1, "item_name": "JS、JP后背板改为单开门", "category_level1": "门变形"},
            {"attachment_price_id": 2, "item_name": "JS、JP后背板改为双开门", "category_level1": "门变形"},
            {"attachment_price_id": 3, "item_name": "JS、JP单开门改为双开门", "category_level1": "门变形"},
            {"attachment_price_id": 4, "item_name": "JA、JE单开门改为双开门", "category_level1": "门变形"},
        ]
        self.refreshes = 0

    def door_counts(self):
        return self._counts

    def selected_product_code(self):
        return self._product

    def update_attachment_view(self):
        self.refreshes += 1


transform_window = DoorTransformWindow()
transform_window._counts = (0, 2)
assert layout_refresh._sync_door_transform_defaults(transform_window)
assert [item["item_name"] for item in transform_window.attachments] == [
    "侧板", "JS、JP单开门改为双开门", "JS、JP后背板改为双开门",
]
assert not any(
    str(rule).startswith(DOOR_TRANSFORMATION_RULE_PREFIX)
    for rule in transform_window.attachment_default_opt_outs
)
assert transform_window.refreshes == 1
assert not layout_refresh._sync_door_transform_defaults(transform_window)
transform_window._product = "JE_SINGLE"
transform_window._counts = (0, 1)
assert layout_refresh._sync_door_transform_defaults(transform_window)
assert [item["item_name"] for item in transform_window.attachments] == [
    "侧板", "JA、JE单开门改为双开门",
]

ganged_transform_window = DoorTransformWindow()
ganged_transform_window.ganged_cabinets = [
    {"width_mm": 200, "depth_mm": 600, "height_mm": 600,
     "single_door_count": 2, "double_door_count": 0},
    {"width_mm": 200, "depth_mm": 600, "height_mm": 600,
     "single_door_count": 0, "double_door_count": 2},
]
ganged_transform_window.attachment_door_transform_context = ("JS_SINGLE", ((1, 0), (1, 0)))
assert layout_refresh._sync_door_transform_defaults(ganged_transform_window)
assert [item["item_name"] for item in ganged_transform_window.attachments] == [
    "侧板",
    "JS、JP后背板改为单开门",
    "JS、JP单开门改为双开门",
    "JS、JP后背板改为双开门",
]

approved_quick_categories = {
    "固定底座": "底座",
    "JP侧板": "侧板",
    "镀锌安装板": "安装板",
    "内门": "内门",
    "玻璃门": "玻璃门",
    "通风顶罩": "通风顶罩",
    "防雨顶": "防雨顶",
    "分段板": "分段板",
    "JK安装板": "JK安装板",
}
for item_name, category in approved_quick_categories.items():
    assert quick_discount_category({"item_name": item_name}) == category
for item_name in ("风机", "门限位器", "接地线", "文件夹", "三排纵梁", "安装板单发", "JK安装板单发", "运费"):
    assert quick_discount_category({"item_name": item_name}) is None

quick_breakdown = quick_discount_breakdown(
    {"total_cost": 4406.29, "attachment_fee": 392},
    [
        {"item_name": "固定底座", "quantity": 1, "unit_price": 100},
        {"item_name": "内门", "quantity": 1, "unit_price": 200},
        {"item_name": "风机", "quantity": 1, "unit_price": 80},
        {"item_name": "接地线", "quantity": 2, "unit_price": 6},
    ],
    0.95,
)
assert math.isclose(quick_breakdown["base_price"], 4014.29)
assert math.isclose(quick_breakdown["eligible_attachment_total"], 300)
assert math.isclose(quick_breakdown["original_price_attachment_total"], 92)
assert math.isclose(quick_breakdown["discounted_total"], 4190.5755)

negative_board = quick_discount_breakdown(
    {"total_cost": 900, "base_price": 1000, "attachment_fee": -100},
    [{
        "item_name": "安装板", "category_level1": "安装板",
        "quantity": 1, "unit_price": 100, "attachment_price_sign": -1,
    }],
    0.9,
)
assert math.isclose(negative_board["listed_attachment_total"], -100)
assert math.isclose(negative_board["eligible_attachment_total"], -100)
assert math.isclose(negative_board["discounted_total"], 810)

print("V3 program rule contracts passed")
