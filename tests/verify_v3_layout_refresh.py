"""Runtime contracts for the current client's attachment browser and pages.

Use the specified AIQuoteDualSystem_layout_v0.exe installation's verified core
with all current source overlays enabled. Retired whole-page layouts must not
be selected to satisfy these tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_ROOT))

core_root = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core_root.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core directory")
baseline_core = ROOT.parent / "AIQuoteDualSystem" / "_internal" / "v3_core"
assert core_root.resolve() == baseline_core.resolve(), (core_root, baseline_core)
assert (baseline_core.parent.parent / "AIQuoteDualSystem_layout_v0.exe").is_file()

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QAbstractButton,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

import layout_refresh  # noqa: E402
import v3_launcher  # noqa: E402


class _LogicalScreen:
    def __init__(self, width: int, height: int):
        self._available = QRect(0, 0, width, height)

    def availableGeometry(self):
        return self._available


class _MinimumWindowProbe:
    def __init__(self, width: int, height: int):
        self._screen = _LogicalScreen(width, height)
        self.minimum = None

    def screen(self):
        return self._screen

    def setMinimumSize(self, width: int, height: int):
        self.minimum = (width, height)


# Windows scaling is already reflected in Qt logical pixels.  Neither a
# 1366x768 display at 125% nor a 1366x768 display at 150% may inherit the old
# fixed 980x700 minimum and push the action area off-screen.
for logical_size in ((1092, 576), (910, 512)):
    minimum_probe = _MinimumWindowProbe(*logical_size)
    layout_refresh._fit_window_minimum_to_screen(minimum_probe)
    assert minimum_probe.minimum[0] <= logical_size[0]
    assert minimum_probe.minimum[1] <= logical_size[1]

# The attachment picker opens larger on roomy desktops and caps its logical
# dimensions to the active desktop at common Windows scaling levels.
for logical_size, expected in {
    (1092, 614): (1060, 582),  # 1366x768 at 125% (representative logical area)
    (910, 512): (878, 480),    # 150%
    (781, 439): (749, 407),    # 175%
    (683, 384): (651, 352),    # 200%
}.items():
    size_probe = _MinimumWindowProbe(*logical_size)
    assert layout_refresh._attachment_dialog_target_size(size_probe) == expected


def buttons_with_text(root, captions: set[str]):
    return [
        button
        for button in root.findChildren(QAbstractButton)
        if button.text().replace("&", "").strip() in captions
    ]


namespace = v3_launcher.load_v3_namespace()
assert namespace["API_URL"] == "https://ai-quote-dual-test.onrender.com/api/quotes/calculate-dual"

remark_builder = namespace["build_standardized_quote_remark"]
manual_remark = "手工录入，碳钢喷塑RAL7035橘纹，前双开门后背板，配风机1个。"
for counts, expected in {
    (1, 0): "前单开门",
    (0, 1): "前双开门",
    (2, 0): "前后单开门",
    (0, 2): "前后双开门",
    (1, 1): "前单开门后双开门",
}.items():
    updated = remark_builder(
        {"single_door_count": counts[0], "double_door_count": counts[1]},
        manual_remark,
    )
    assert updated == manual_remark.replace("前双开门后背板", expected), updated

attachment_dialog_class = namespace["AttachmentDialog"]
assert attachment_dialog_class._default_selection_filters_installed is True
original_attachment_load = attachment_dialog_class.load_catalog
attachment_dialog_class.load_catalog = lambda self, _api_url: None

runtime_calculator = namespace["FormulaDatabaseCalculator"]()
assert runtime_calculator.DETAIL_ROWS["JP_SINGLE"] == (5, 43, 29, 3, 2)
assert runtime_calculator.DOOR_CONTROL_CELLS["JE_SINGLE"] == ("B16", "B17")
runtime_calculator.load_template({
    "template": {
        "template_code": "JS_SINGLE",
        "option_cells": {"defaults": {"B14": 1.5}},
        "rules": [{
            "source_row_no": 5,
            "raw_rule": {
                "values": [],
                "formulas": [
                    "", "",
                    '=IF(AND(B14=1.5,1000>=B8>=350,B7<1000),"1","2")',
                ],
            },
            "include_material_cost": False,
            "include_spray_area": False,
        }],
    }
})
assert "1000>=(B8>=350)" in runtime_calculator.sheets["JS_SINGLE"]["formulas"]["F5"]
runtime_calculator.load_template({
    "template": {
        "template_code": "JP_DOUBLE",
        "option_cells": {"defaults": {"B15": 0}},
        "rules": [{
            "source_row_no": 35,
            "raw_rule": {
                "values": [],
                "formulas": [
                    "", "", "=$B$37-88", "", "", "", "", "",
                    "=IF(TRUE,($B$9/$B$15-1)*$B$15,0)",
                ],
            },
            "include_material_cost": False,
            "include_spray_area": False,
        }],
    }
})
jp_runtime_formulas = runtime_calculator.sheets["JP_DOUBLE"]["formulas"]
assert jp_runtime_formulas["F35"] == "$B$7-88", jp_runtime_formulas["F35"]
assert "$B$9/$B$15" not in jp_runtime_formulas["L35"], jp_runtime_formulas["L35"]
runtime_calculator.sheets["JS_SINGLE"] = {
    "cells": {
        "E5": "安装纵梁", "H5": 2, "M5": 1.07794944,
        "N5": "镀锌板", "Y5": 0,
    },
    "formulas": {},
}
runtime_weight, runtime_area = runtime_calculator.calculate(
    "JS_SINGLE", 800, 800, 800, 1, 0
)
assert abs(runtime_weight - 1.07794944) < 1e-10, runtime_weight
assert runtime_area == 0, runtime_area
assert layout_refresh._formula_workbook_value(80.72750144609303) == "80.7"
assert layout_refresh._formula_workbook_value(8.557817499999016) == "8.6"
runtime_calculator.sheets = {
    "JE_SINGLE": {
        "cells": {"H5": 7, "M5": 12, "N5": "", "Y5": 1},
        "formulas": {"E5": 'IF(B16=1,"MS828锁杆","")'},
    }
}
runtime_weight, runtime_area = runtime_calculator.calculate(
    "JE_SINGLE", 600, 2000, 300, 1, 0
)
assert runtime_weight == 12, runtime_weight
assert runtime_area == 0.5, runtime_area

# The layout contract is offline.  Product/company loading is separately
# covered by API tests and must not contact Render or Neon from this check.
namespace["MainWindow"].load_catalogs = lambda self: None

app = QApplication.instance() or QApplication(sys.argv[:1])
namespace["install_application_font"](app)
assert layout_refresh._install_qt_chinese_translator()
standard_message = QMessageBox()
standard_message.setStandardButtons(
    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
)
standard_captions = {button.text().replace("&", "") for button in standard_message.buttons()}
assert "确定" in standard_captions, standard_captions
assert "取消" in standard_captions, standard_captions
assert "OK" not in standard_captions and "Cancel" not in standard_captions

artifact_dir_text = os.environ.get("AI_QUOTE_UI_ARTIFACT_DIR", "").strip()
artifact_dir = Path(artifact_dir_text) if artifact_dir_text else None
if artifact_dir is not None:
    artifact_dir.mkdir(parents=True, exist_ok=True)

attachment_parent = QWidget()
attachment_parent.quote_spec_edit = QLineEdit(attachment_parent)
attachment_parent.quote_spec_edit.setText("760*500*(960+100)")
attachment_parent.selected_product_code = lambda: "JP_SINGLE"
attachment_parent._door_counts = (1, 0)
attachment_parent.door_counts = lambda: attachment_parent._door_counts
attachment_dialog = attachment_dialog_class(
    [],
    api_url="http://127.0.0.1:1",
    parent=attachment_parent,
    target_dimensions=(760, 960, 500),
)
attachment_dialog.catalog = [
    {
        "attachment_price_id": 1,
        "item_name": "固定底座",
        "model_code": "BASE-FIXED-100",
        "price": 100,
        "category_level1": "底座",
        "category_level2": "固定底座",
        "width_mm": 760,
        "height_mm": 100,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 2,
        "item_name": "活动底座",
        "model_code": "BASE-MOBILE-100",
        "price": 110,
        "category_level1": "底座",
        "category_level2": "活动底座",
        "width_mm": 760,
        "height_mm": 100,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 3,
        "item_name": "侧板",
        "model_code": "JP680950",
        "price": 40,
        "category_level1": "侧板",
        "height_mm": 960,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 6,
        "item_name": "三排安装梁",
        "model_code": "JP760250",
        "price": 25,
        "category_level1": "安装附件",
        "category_level2": "三排纵梁",
    },
    {
        "attachment_price_id": 61,
        "item_name": "固定立柱",
        "price": 35,
        "category_level1": "安装附件",
        "category_level2": "固定立柱",
        "height_mm": 960,
    },
    {
        "attachment_price_id": 4,
        "item_name": "安装板",
        "model_code": "安装板",
        "price": 75,
        "category_level1": "安装板",
        "category_level2": "安装板",
        "width_mm": 760,
        "height_mm": 960,
        # Installation-board matching intentionally ignores cabinet depth.
        "depth_mm": 100,
    },
    {
        "attachment_price_id": 5,
        "item_name": "JK安装板",
        "model_code": "JK安装板",
        "price": 80,
        "category_level1": "安装板",
        "category_level2": "JK安装板",
        "width_mm": 760,
        "height_mm": 960,
        # Installation-board matching intentionally ignores cabinet depth.
        "depth_mm": 100,
    },
    {
        "attachment_price_id": 7,
        "item_name": "照明灯/行程开关",
        "price": 50,
        "category_level1": "灯开关",
    },
    {
        "attachment_price_id": 8,
        "item_name": "A3资料盒",
        "price": 60,
        "category_level1": "资料盒",
    },
    {
        "attachment_price_id": 9,
        "item_name": "A4资料盒",
        "price": 30,
        "category_level1": "资料盒",
    },
    {
        "item_name": "过滤网FU-9803A",
        "model_code": "过滤网FU-9803A",
        "variant": "7035色",
        "price": 15,
        "category_level1": "滤网",
        "category_level2": "过滤网",
        "category_level3": "过滤网FU-9803A",
    },
    {
        "attachment_price_id": 10,
        "item_name": "门限位器",
        "price": 25,
        "category_level1": "门限位器",
    },
    {
        "attachment_price_id": 11,
        "item_name": "门加强筋",
        "price": 20,
        "category_level1": "门加强筋",
    },
    {
        "attachment_price_id": 12,
        "item_name": "接地线",
        "model_code": "红绿线",
        "price": 6,
        "category_level1": "接地线",
        "category_level2": "红绿线",
    },
    {
        "attachment_price_id": 13,
        "item_name": "接地线",
        "model_code": "编织带",
        "price": 8,
        "category_level1": "接地线",
        "category_level2": "编织带",
    },
    {
        "attachment_price_id": 14,
        "item_name": "铜排",
        "model_code": "所有型号",
        "price": 50,
        "unit": "件",
        "category_level1": "铜排",
    },
    {
        "attachment_price_id": 15,
        "item_name": "并柜件",
        "model_code": "",
        "price": 60,
        "unit": "件",
        "category_level1": "并柜件",
        "category_level2": "",
    },
    {
        "attachment_price_id": 16,
        "item_name": "内门",
        "model_code": "JP-INNER-760",
        "price": 120,
        "category_level1": "控制柜附件",
        "category_level2": "内门",
        "width_mm": 760,
        "height_mm": 960,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 17,
        "item_name": "防雨顶",
        "model_code": "JP-RAIN-760",
        "price": 130,
        "category_level1": "控制柜附件",
        "category_level2": "防雨顶",
        "width_mm": 760,
        "height_mm": 960,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 18,
        "item_name": "通风顶罩",
        "model_code": "JP-VENT-760",
        "price": 140,
        "category_level1": "控制柜附件",
        "category_level2": "通风顶罩",
        "width_mm": 760,
        "height_mm": 120,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 19,
        "item_name": "JK安装板",
        "model_code": "JK-CONTROL-800",
        "price": 85,
        "category_level1": "控制箱附件",
        "category_level2": "JK安装板",
        "width_mm": 800,
        "height_mm": 1000,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 20,
        "item_name": "内门",
        "model_code": "JK-INNER-800",
        "price": 125,
        "category_level1": "控制箱附件",
        "category_level2": "内门",
        "width_mm": 800,
        "height_mm": 1000,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 21,
        "item_name": "防雨顶",
        "model_code": "JK-RAIN-800",
        "price": 135,
        "category_level1": "控制箱附件",
        "category_level2": "防雨顶",
        "width_mm": 800,
        "height_mm": 1000,
        "depth_mm": 500,
    },
    {
        "item_name": "保留配置项",
        "price": 10,
        "category_level1": "配置变形",
    },
    {
        "item_name": "JS、JP后背板改为单开门",
        "model_code": "所有型号",
        "price": 150,
        "category_level1": "门变形",
        "category_level2": "JS、JP后背板改为单开门",
    },
    {
        "item_name": "未来附件",
        "price": 1,
        "category_level1": "未来分类",
    },
]
assert attachment_dialog.prepare_default_selections() == 7
limiter_attachment = next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "门限位器"
)
assert limiter_attachment["quantity"] == 1
assert all(
    item.get("quantity") == 1
    for item in attachment_dialog.attachments
    if item.get("item_name") != "门限位器"
)
attachment_dialog.rebuild_table()
attachment_dialog.show()
app.processEvents()
expected_attachment_size = layout_refresh._attachment_dialog_target_size(attachment_dialog)
assert (attachment_dialog.width(), attachment_dialog.height()) == expected_attachment_size
assert attachment_dialog.width() <= layout_refresh.ATTACHMENT_DIALOG_TARGET_WIDTH
assert attachment_dialog.height() <= layout_refresh.ATTACHMENT_DIALOG_TARGET_HEIGHT
assert (
    attachment_dialog.minimumWidth()
    == min(expected_attachment_size[0], layout_refresh.ATTACHMENT_DIALOG_MIN_WIDTH)
)
assert (
    attachment_dialog.minimumHeight()
    == min(expected_attachment_size[1], layout_refresh.ATTACHMENT_DIALOG_MIN_HEIGHT)
)
assert attachment_dialog.maximumWidth() == expected_attachment_size[0]
assert attachment_dialog.maximumHeight() == expected_attachment_size[1]
assert len(buttons_with_text(attachment_dialog, {"确认选择"})) == 1
assert len(buttons_with_text(attachment_dialog, {"取消"})) == 1
assert not buttons_with_text(attachment_dialog, {"Cancel"})
selection_status = attachment_dialog.findChild(QFrame, "attachmentSelectionStatusBar")
assert selection_status is not None
assert attachment_dialog.selection_hint.parentWidget() is selection_status
assert "background:#ffffff" in selection_status.styleSheet().replace(" ", "").lower()
assert "color:#174a73" in attachment_dialog.selection_hint.styleSheet().replace(" ", "").lower()
attachment_dialog.resize(1100, 800)
app.processEvents()
assert (attachment_dialog.width(), attachment_dialog.height()) == expected_attachment_size
assert attachment_dialog.search_edit.geometry().top() < attachment_dialog.category_breadcrumb.geometry().top()
assert attachment_dialog.objectName() == "attachmentDialog"
assert attachment_dialog.search_edit.objectName() == "attachmentSearchInput"
assert attachment_dialog.table.objectName() == "attachmentCatalogTable"
assert attachment_dialog.add_attachment_catalog_button.accessibleName() == "新增附件到附件库"

def attachment_category_buttons():
    return [
        button
        for button in attachment_dialog.findChildren(QPushButton, "attachmentCategoryCard")
        if button.isVisible()
    ]


def attachment_category_button(label: str):
    return next(
        button for button in attachment_category_buttons()
        if button.property("attachmentCategoryValue") == label
    )


level1_buttons = attachment_category_buttons()
level1_values = [button.property("attachmentCategoryValue") for button in level1_buttons]
requested_level1_order = (
    "侧板", "安装板", "安装附件", "底座", "灯开关", "资料盒", "风机",
    "滤网", "门变形", "并柜件",
)
assert [value for value in level1_values if value in requested_level1_order] == [
    "侧板", "安装板", "安装附件", "底座", "灯开关", "资料盒", "滤网", "门变形", "并柜件",
]
assert all("一级分类：" in button.text() and "名称：" in button.text() for button in level1_buttons)
assert all(button.parentWidget().minimumHeight() >= 82 for button in level1_buttons)
positions = [
    attachment_dialog.category_grid.getItemPosition(
        attachment_dialog.category_grid.indexOf(button.parentWidget())
    )[:2]
    for button in level1_buttons
]
expected_positions = [
    (index, 0)
    for index in range(len(level1_buttons))
]
assert positions == expected_positions, positions
row_count = max(row for row, _column in positions) + 1
assert attachment_dialog.category_scroll_content.minimumHeight() >= (
    row_count * 82
    + max(0, row_count - 1) * attachment_dialog.category_grid.verticalSpacing()
)
assert attachment_dialog.table.isHidden()
quick_match_buttons = attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
assert len(quick_match_buttons) == 7
assert any(button.text() == "默认已选择  ·  固定 · 高 100 mm" for button in quick_match_buttons)
assert not any("A3资料盒" in button.text() or "A4资料盒" in button.text() for button in quick_match_buttons)
assert any(button.text() == "默认已选择  ·  门加强筋 · 数量：1 个" for button in quick_match_buttons)
assert any(button.text() == "默认已选择  ·  红绿线" for button in quick_match_buttons)
assert any(button.text() == "默认已选择  ·  门限位器 · 数量：1 个" for button in quick_match_buttons)
assert any(button.text() == "默认已选择  ·  铜排 · 默认数量：1 件" for button in quick_match_buttons)
assert all(button.parentWidget().objectName() == "attachmentSelectionPane" for button in quick_match_buttons)
explicit_quick_buttons = [
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatch")
    if button.isVisible() and button.property("attachmentQuickRule")
]
assert {
    button.property("attachmentQuickRule") for button in explicit_quick_buttons
} >= {
    "installation_board", "three_row_installation_beam", "fixed_column",
    "a3_folder", "a4_folder", "ganged_connector",
    "inner_door", "rain_cover", "ventilation_hood",
}
assert not any(
    button.property("attachmentQuickRule") == "jk_installation_board"
    for button in attachment_dialog.findChildren(QPushButton)
    if button.isVisible()
)
assert not any(
    button.property("attachmentQuickRule") == "ganged_fill_installation_board"
    for button in attachment_dialog.findChildren(QPushButton)
    if button.isVisible()
)
assert all("快速匹配未选择" in button.text() for button in explicit_quick_buttons)
assert not any(
    item.get("item_name") in {"安装板", "JK安装板", "三排安装梁", "固定立柱", "A3资料盒", "A4资料盒", "并柜件"}
    for item in attachment_dialog.attachments
)
for quick_button in quick_match_buttons:
    shell = quick_button.parentWidget().parentWidget()
    category_button = shell.findChild(QPushButton, "attachmentCategoryCard")
    assert category_button is not None
    assert quick_button.mapTo(attachment_dialog, QPoint(0, 0)).x() >= (
        category_button.mapTo(attachment_dialog, QPoint(category_button.width(), 0)).x()
    )


def visible_quick_rule_button(rule: str):
    return next(
        button for button in attachment_dialog.findChildren(QPushButton)
        if button.isVisible() and button.property("attachmentQuickRule") == rule
    )


# All requested shortcuts are opt-in, independently toggleable, green only
# while selected, and reuse one catalogue row rather than duplicating it.
explicit_rules = {
    "installation_board": "安装板",
    "three_row_installation_beam": "三排安装梁",
    "fixed_column": "固定立柱",
    "a3_folder": "A3资料盒",
    "a4_folder": "A4资料盒",
    "ganged_connector": "并柜件",
    "inner_door": "内门",
    "rain_cover": "防雨顶",
    "ventilation_hood": "通风顶罩",
}
attachment_dialog.request_ventilation_hood_height = lambda _initial: (120.0, True)
quick_selection_change_count = [0]
attachment_dialog.attachment_selection_changed = lambda: quick_selection_change_count.__setitem__(
    0, quick_selection_change_count[0] + 1
)
for rule, expected_name in explicit_rules.items():
    saved_scroll_value = None
    quick_button_before = visible_quick_rule_button(rule)
    if rule == "a3_folder":
        scroll_bar = attachment_dialog.category_scroll.verticalScrollBar()
        saved_scroll_value = min(180, scroll_bar.maximum())
        scroll_bar.setValue(saved_scroll_value)
    quick_button_before.click()
    app.processEvents()
    if saved_scroll_value is not None:
        assert attachment_dialog.category_scroll.verticalScrollBar().value() == saved_scroll_value
        assert visible_quick_rule_button(rule) is quick_button_before
    selected_button = visible_quick_rule_button(rule)
    assert selected_button.objectName() == "attachmentQuickMatchSelected"
    assert "快速匹配已选择" in selected_button.text()
    assert sum(
        item.get("item_name") == expected_name
        for item in attachment_dialog.attachments
    ) == 1
    if rule == "ganged_connector":
        selected = next(
            item for item in attachment_dialog.attachments
            if item.get("item_name") == "并柜件"
        )
        assert selected["attachment_price_id"] == 15
        assert selected.get("matched_price", selected.get("price")) == 60
        # Repeated browser refreshes must retain one catalogue row, never duplicate it.
        attachment_dialog.refresh_category_browser()
        attachment_dialog.refresh_category_browser()
        app.processEvents()
        assert sum(
            item.get("item_name") == "并柜件"
            for item in attachment_dialog.attachments
        ) == 1
    if rule == "ventilation_hood":
        selected = next(
            item for item in attachment_dialog.attachments
            if item.get("item_name") == "通风顶罩"
        )
        assert selected["size_match_target_height_mm"] == 120
        assert selected["attachment_price_id"] == 18
assert {
    item.get("item_name") for item in attachment_dialog.attachments
} >= set(explicit_rules.values())
assert quick_selection_change_count[0] == len(explicit_rules)
for rule, expected_name in explicit_rules.items():
    visible_quick_rule_button(rule).click()
    app.processEvents()
    unselected_button = visible_quick_rule_button(rule)
    assert unselected_button.objectName() == "attachmentQuickMatch"
    assert "快速匹配未选择" in unselected_button.text()
    assert not any(
        item.get("item_name") == expected_name
        for item in attachment_dialog.attachments
    )

# A ganged cabinet receives one independently size-matched fixed base for
# each split row.  Those selection rows do not multiply by the split count a
# second time, but each still follows the number of complete ganged cabinets.
ganged_attachment_parent = QWidget()
ganged_attachment_parent.quote_spec_edit = QLineEdit(ganged_attachment_parent)
ganged_attachment_parent.quote_spec_edit.setText("(600+900)*500*(1800+100)")
ganged_attachment_parent.selected_product_code = lambda: "JP_SINGLE"
ganged_attachment_parent.door_counts = lambda: (1, 0)
ganged_attachment_parent.ganged_cabinets = [
    {
        "width_mm": 600,
        "depth_mm": 500,
        "height_mm": 1800,
        "base_height_mm": 100,
        "single_door_count": 1,
        "double_door_count": 0,
    },
    {
        "width_mm": 900,
        "depth_mm": 500,
        "height_mm": 1800,
        "base_height_mm": 100,
        "single_door_count": 1,
        "double_door_count": 0,
    },
]
ganged_attachment_dialog = attachment_dialog_class(
    [],
    api_url="http://127.0.0.1:1",
    parent=ganged_attachment_parent,
    target_dimensions=(600, 1800, 500),
)
ganged_attachment_dialog.catalog = [
    {
        "attachment_price_id": 101,
        "item_name": "固定底座",
        "model_code": "BASE-600",
        "price": 100,
        "category_level1": "底座",
        "category_level2": "固定底座",
        "width_mm": 600,
        "height_mm": 100,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 102,
        "item_name": "固定底座",
        "model_code": "BASE-900",
        "price": 140,
        "category_level1": "底座",
        "category_level2": "固定底座",
        "width_mm": 900,
        "height_mm": 100,
        "depth_mm": 500,
    },
    {
        "attachment_price_id": 103,
        "item_name": "填充安装板",
        "price": 80,
        "category_level1": "配置变形",
        "category_level2": "",
    },
]
assert ganged_attachment_dialog.prepare_default_selections() == 2
ganged_bases = [
    item for item in ganged_attachment_dialog.attachments
    if item.get("ganged_fixed_base_match")
]
assert [item["model_code"] for item in ganged_bases] == ["BASE-600", "BASE-900"]
assert [item["ganged_fixed_base_index"] for item in ganged_bases] == [0, 1]
assert [item["quantity"] for item in ganged_bases] == [1, 1]
assert [layout_refresh.final_attachment_quantity(item, 3, 2) for item in ganged_bases] == [3, 3]
ganged_attachment_dialog.rebuild_table()
ganged_attachment_dialog.show()
app.processEvents()
def visible_ganged_quick_rule_button(rule: str):
    return next(
        button for button in ganged_attachment_dialog.findChildren(QPushButton)
        if button.isVisible() and button.property("attachmentQuickRule") == rule
    )


fill_board_quick = visible_ganged_quick_rule_button(
    "ganged_fill_installation_board"
)
assert fill_board_quick.objectName() == "attachmentQuickMatch"
assert "快速匹配未选择" in fill_board_quick.text()
fill_board_quick.click()
app.processEvents()
assert visible_ganged_quick_rule_button(
    "ganged_fill_installation_board"
).objectName() == "attachmentQuickMatchSelected"
assert sum(
    item.get("attachment_price_id") == 103
    for item in ganged_attachment_dialog.attachments
) == 1
ganged_attachment_dialog.refresh_category_browser()
app.processEvents()
assert sum(
    item.get("attachment_price_id") == 103
    for item in ganged_attachment_dialog.attachments
) == 1
visible_ganged_quick_rule_button(
    "ganged_fill_installation_board"
).click()
app.processEvents()
assert visible_ganged_quick_rule_button(
    "ganged_fill_installation_board"
).objectName() == "attachmentQuickMatch"
assert not any(
    item.get("attachment_price_id") == 103
    for item in ganged_attachment_dialog.attachments
)
assert [item.get("ganged_fixed_base_index") for item in ganged_attachment_dialog.attachments] == [0, 1], ganged_attachment_dialog.attachments
ganged_table_sources = [
    ganged_attachment_dialog.table.item(row, ganged_attachment_dialog.COL_CHECK).data(Qt.ItemDataRole.UserRole)
    for row in range(ganged_attachment_dialog.table.rowCount())
    if ganged_attachment_dialog.table.item(row, ganged_attachment_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked
]
assert [item.get("ganged_fixed_base_index") for item in ganged_table_sources] == [0, 1], ganged_table_sources
collected_ganged_bases = ganged_attachment_dialog.collect_attachments(show_errors=False)
assert collected_ganged_bases is not None
assert [item.get("ganged_fixed_base_index") for item in collected_ganged_bases] == [0, 1], collected_ganged_bases

same_base_parent = QWidget()
same_base_parent.quote_spec_edit = QLineEdit(same_base_parent)
same_base_parent.quote_spec_edit.setText("(600+600)*500*(1800+100)")
same_base_parent.selected_product_code = lambda: "JP_SINGLE"
same_base_parent.door_counts = lambda: (1, 0)
same_base_parent.ganged_cabinets = [
    {**row, "width_mm": 600}
    for row in ganged_attachment_parent.ganged_cabinets
]
same_base_dialog = attachment_dialog_class(
    [], api_url="http://127.0.0.1:1", parent=same_base_parent,
    target_dimensions=(600, 1800, 500),
)
same_base_dialog.catalog = [dict(ganged_attachment_dialog.catalog[0])]
assert same_base_dialog.prepare_default_selections() == 2
same_base_dialog.rebuild_table()
same_base_collected = same_base_dialog.collect_attachments(show_errors=False)
assert same_base_collected is not None
assert len(same_base_collected) == 2
assert [item.get("ganged_fixed_base_index") for item in same_base_collected] == [0, 1]
assert [layout_refresh.final_attachment_quantity(item, 3, 2) for item in same_base_collected] == [3, 3]

# Entering the door-transformation category is an explicit override gesture:
# it removes only automatic door rows, keeps every earlier manual row and
# prevents unrelated navigation/search rebuilds from restoring the default.
door_parent = QWidget()
door_parent.quote_spec_edit = QLineEdit(door_parent)
door_parent.quote_spec_edit.setText("1500*300*1800")
door_parent.selected_product_code = lambda: "JP_SINGLE"
door_parent._door_counts = (2, 0)
door_parent.door_counts = lambda: door_parent._door_counts
manual_keep = {
    "attachment_price_id": 201,
    "item_name": "人工保留配置",
    "model_code": "MANUAL-KEEP",
    "price": 12,
    "quantity": 2,
    "category_level1": "配置变形",
    "selection_source": "manual",
}
door_dialog = attachment_dialog_class(
    [dict(manual_keep)],
    api_url="http://127.0.0.1:1",
    parent=door_parent,
    target_dimensions=(1500, 1800, 300),
)
door_dialog.catalog = [
    dict(manual_keep),
    {
        "attachment_price_id": 202,
        "item_name": "JS、JP后背板改为单开门",
        "model_code": "DOOR-AUTO",
        "price": 150,
        "category_level1": "门变形",
    },
    {
        "attachment_price_id": 203,
        "item_name": "JS、JP后背板改为双开门",
        "model_code": "DOOR-MANUAL",
        "price": 270,
        "category_level1": "门变形",
    },
    {
        "attachment_price_id": 204,
        "item_name": "搜索选择附件",
        "model_code": "SEARCH-MANUAL",
        "price": 30,
        "category_level1": "控制柜附件",
    },
    {
        "attachment_price_id": 205,
        "item_name": "三级风机附件",
        "model_code": "FAN-L3",
        "price": 45,
        "category_level1": "滤网",
        "category_level2": "风机",
        "category_level3": "三级风机附件",
    },
]
assert door_dialog.prepare_default_selections() == 1
door_dialog.rebuild_table()
door_dialog.show()
app.processEvents()
automatic_door = next(
    item for item in door_dialog.attachments
    if item.get("item_name") == "JS、JP后背板改为单开门"
)
assert automatic_door["selection_source"] == "automatic"

def visible_dialog_category_button(dialog, label: str):
    return next(
        button for button in dialog.findChildren(QPushButton, "attachmentCategoryCard")
        if button.isVisible() and button.property("attachmentCategoryValue") == label
    )


def visible_dialog_quick_rule_button(dialog, rule: str):
    return next(
        button for button in dialog.findChildren(QPushButton)
        if button.isVisible() and button.property("attachmentQuickRule") == rule
    )


visible_dialog_category_button(door_dialog, "门变形").click()
app.processEvents()
assert not door_dialog.table.isHidden()
assert not any(
    item.get("item_name") == "JS、JP后背板改为单开门"
    for item in door_dialog.attachments
)
assert any(item.get("item_name") == "人工保留配置" for item in door_dialog.attachments)
assert any(
    str(rule).startswith("door_transformation:")
    for rule in door_dialog.default_selection_opt_outs
)
door_dialog.search_edit.setText("DOOR-MANUAL")
app.processEvents()
door_manual_row = next(
    row for row in range(door_dialog.table.rowCount())
    if not door_dialog.table.isRowHidden(row)
    and door_dialog.table.item(row, door_dialog.COL_NAME).text()
    == "JS、JP后背板改为双开门"
)
door_dialog.table.item(
    door_manual_row, door_dialog.COL_CHECK
).setCheckState(Qt.CheckState.Checked)
app.processEvents()
door_dialog.search_edit.clear()
door_dialog.back_attachment_category()
app.processEvents()
manual_door = next(
    item for item in door_dialog.attachments
    if item.get("item_name") == "JS、JP后背板改为双开门"
)
assert manual_door["selection_source"] == "manual"
door_dialog.rebuild_table()
app.processEvents()
assert not any(
    item.get("item_name") == "JS、JP后背板改为单开门"
    for item in door_dialog.attachments
)
assert any(
    item.get("item_name") == "JS、JP后背板改为双开门"
    for item in door_dialog.attachments
)

# A search selection and a third-level selection both survive the return to
# level one and each receives its own green manual-selection card.
door_dialog.search_edit.setText("SEARCH-MANUAL")
app.processEvents()
search_row = next(
    row for row in range(door_dialog.table.rowCount())
    if not door_dialog.table.isRowHidden(row)
)
door_dialog.table.item(
    search_row, door_dialog.COL_CHECK
).setCheckState(Qt.CheckState.Checked)
app.processEvents()
door_dialog.search_edit.clear()
door_dialog.refresh_category_browser()
app.processEvents()
visible_dialog_category_button(door_dialog, "滤网").click()
app.processEvents()
assert not door_dialog.table.isHidden()
fan_row = next(
    row for row in range(door_dialog.table.rowCount())
    if not door_dialog.table.isRowHidden(row)
)
door_dialog.table.item(
    fan_row, door_dialog.COL_CHECK
).setCheckState(Qt.CheckState.Checked)
app.processEvents()
while door_dialog.category_selection:
    door_dialog.back_attachment_category()
app.processEvents()
manual_cards = [
    button for button in door_dialog.findChildren(
        QPushButton, "attachmentManualSelection"
    )
    if button.isVisible()
]
manual_card_texts = [button.text() for button in manual_cards]
for expected in (
    "人工保留配置", "JS、JP后背板改为双开门", "搜索选择附件", "三级风机附件",
):
    assert sum(expected in text for text in manual_card_texts) == 1, manual_card_texts
assert all("数量" in text and "元" in text for text in manual_card_texts)
assert "#e3f3e9" in door_dialog.attachment_category_panel.styleSheet().lower()
if artifact_dir is not None:
    assert door_dialog.grab().save(
        str(artifact_dir / "v3_manual_attachment_cards.png")
    )

before_manual_total = sum(
    layout_refresh.quick_attachment_line_amount(item)
    for item in door_dialog.attachments
)
door_card = next(
    button for button in manual_cards
    if "JS、JP后背板改为双开门" in button.text()
)
door_card.click()
app.processEvents()
assert not any(
    item.get("item_name") == "JS、JP后背板改为双开门"
    for item in door_dialog.attachments
)
assert all(
    any(item.get("item_name") == expected for item in door_dialog.attachments)
    for expected in ("人工保留配置", "搜索选择附件", "三级风机附件")
)
after_manual_total = sum(
    layout_refresh.quick_attachment_line_amount(item)
    for item in door_dialog.attachments
)
assert before_manual_total - after_manual_total == 270
door_dialog.close()
door_parent.close()

# Installation-board matching is opt-in from the first-level card. Opening the
# library displays the gray action but does not select a board.
attachment_dialog.prepare_default_selections()
attachment_dialog.rebuild_table()
while attachment_dialog.category_selection:
    attachment_dialog.back_attachment_category()
app.processEvents()
assert not any(
    item.get("item_name") in {"安装板", "JK安装板"}
    for item in attachment_dialog.attachments
)
installation_card_button = attachment_category_button("安装板")
installation_card = installation_card_button.parentWidget()
board_quick = next(
    button for button in installation_card.findChildren(QPushButton, "attachmentQuickMatch")
    if button.isVisible() and button.property("attachmentQuickRule") == "installation_board"
)
assert "快速匹配未选择" in board_quick.text()
attachment_category_button("安装板").click()
app.processEvents()
attachment_category_button("安装板").click()
app.processEvents()
board_row = next(
    row for row in range(attachment_dialog.table.rowCount())
    if attachment_dialog.table.item(row, attachment_dialog.COL_NAME).text() == "安装板"
)
board_check = attachment_dialog.table.item(board_row, attachment_dialog.COL_CHECK)
board_check.setCheckState(Qt.CheckState.Checked)
app.processEvents()
assert "按柜体宽、高精确匹配安装板" in attachment_dialog.catalog_hint.text()
board_spec_text = attachment_dialog.table.item(
    board_row, attachment_dialog.COL_SPEC
).text()
assert board_spec_text == "760 × 960 mm", board_spec_text
if artifact_dir is not None:
    assert attachment_dialog.grab().save(
        str(artifact_dir / "v3_installation_board_exact_match.png")
    )
while attachment_dialog.category_selection:
    attachment_dialog.back_attachment_category()
app.processEvents()
board_summary = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentManualSelection")
    if button.isVisible() and "安装板" in button.text()
)
assert board_summary.text().startswith("人工已选择  ·  安装板  ·  ")
assert not attachment_dialog.findChildren(QPushButton, "attachmentPriceSignPositive")
assert not attachment_dialog.findChildren(QPushButton, "attachmentPriceSignNegative")
board_source = attachment_dialog.table.item(
    board_row, attachment_dialog.COL_CHECK
).data(Qt.ItemDataRole.UserRole)
assert board_source["size_match_exact"] is True
assert board_source["size_match_target_width_mm"] == 760
assert board_source["size_match_target_height_mm"] == 960
assert board_source["size_match_target_depth_mm"] == 500
assert board_source["size_match_depth_mm"] == 100
assert board_source.get("attachment_price_sign", 1) == 1
assert attachment_dialog.table.item(board_row, attachment_dialog.COL_PRICE).text() == "75"
selected_board = next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "安装板"
)
fresh_board = next(
    item for item in attachment_dialog.collect_attachments(False)
    if item.get("item_name") == "安装板"
)
assert fresh_board["attachment_price_sign"] == 1, fresh_board
assert selected_board["attachment_price_sign"] == 1, attachment_dialog.attachments
assert selected_board["matched_price"] == 75

# Product routing is enforced at the interaction boundary as well: on a JK
# product, even deliberately clicking the ordinary board branch resolves to
# the JK board row and leaves no ordinary board selected.
jk_parent = QWidget()
jk_parent.quote_spec_edit = QLineEdit(jk_parent)
jk_parent.quote_spec_edit.setText("800*500*1000")
jk_parent.selected_product_code = lambda: "JK"
jk_parent.door_counts = lambda: (1, 0)
jk_board_dialog = attachment_dialog_class(
    [],
    api_url="http://127.0.0.1:1",
    parent=jk_parent,
    target_dimensions=(800, 1000, 500),
)
jk_board_dialog.catalog = [
    dict(item) for item in attachment_dialog.catalog
    if item.get("item_name") in {"安装板", "JK安装板", "内门", "防雨顶"}
]
jk_board_dialog.rebuild_table()
jk_board_dialog.show()
app.processEvents()
visible_dialog_category_button(jk_board_dialog, "安装板").click()
app.processEvents()
visible_dialog_category_button(jk_board_dialog, "安装板").click()
app.processEvents()
ordinary_board_row = next(
    row for row in range(jk_board_dialog.table.rowCount())
    if jk_board_dialog.table.item(row, jk_board_dialog.COL_NAME).text() == "安装板"
)
jk_board_dialog.table.item(
    ordinary_board_row, jk_board_dialog.COL_CHECK
).setCheckState(Qt.CheckState.Checked)
app.processEvents()
checked_board_names = [
    jk_board_dialog.table.item(row, jk_board_dialog.COL_NAME).text()
    for row in range(jk_board_dialog.table.rowCount())
    if jk_board_dialog.table.item(row, jk_board_dialog.COL_CHECK).checkState()
    == Qt.CheckState.Checked
]
assert checked_board_names == ["JK安装板"], checked_board_names
assert "匹配最相近安装板" in jk_board_dialog.catalog_hint.text()
jk_selected = next(
    item for item in jk_board_dialog.attachments
    if item.get("item_name") == "JK安装板"
)
assert jk_selected["size_match_exact"] is False
assert jk_selected["size_match_target_perimeter"] == 3600
assert jk_selected["size_match_perimeter"] == 3440
assert jk_selected["unit_price_override"] == round(80 * 3600 / 3440, 6)
while jk_board_dialog.category_selection:
    jk_board_dialog.back_attachment_category()
app.processEvents()
assert any(
    button.isVisible() and button.property("attachmentCategoryValue") == "控制箱附件"
    for button in jk_board_dialog.findChildren(QPushButton, "attachmentCategoryCard")
), [
    button.property("attachmentCategoryValue")
    for button in jk_board_dialog.findChildren(QPushButton, "attachmentCategoryCard")
    if button.isVisible()
]
assert visible_dialog_quick_rule_button(jk_board_dialog, "jk_installation_board").objectName() == "attachmentQuickMatch"
visible_dialog_quick_rule_button(jk_board_dialog, "jk_installation_board").click()
app.processEvents()
assert visible_dialog_quick_rule_button(jk_board_dialog, "jk_installation_board").objectName() == "attachmentQuickMatchSelected"
assert sum(
    item.get("attachment_price_id") == 19
    for item in jk_board_dialog.attachments
) == 1
assert any(
    button.isVisible() and "JK安装板" in button.text()
    for button in jk_board_dialog.findChildren(QPushButton, "attachmentManualSelection")
)
if artifact_dir is not None:
    assert jk_board_dialog.grab().save(
        str(artifact_dir / "v3_jk_installation_board_routing.png")
    )
jk_board_dialog.close()
jk_parent.close()

limiter_row = next(
    row for row in range(attachment_dialog.table.rowCount())
    if attachment_dialog.table.item(row, attachment_dialog.COL_NAME).text() == "门限位器"
)
attachment_dialog.table.item(limiter_row, attachment_dialog.COL_QUANTITY).setText("7")
app.processEvents()
assert "door_limiter" in attachment_dialog.default_quantity_manual_overrides
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "门限位器"
)["quantity"] == 7
attachment_dialog.rebuild_table()
app.processEvents()
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "门限位器"
)["quantity"] == 7
limiter_manual = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchManual")
    if button.isVisible() and "门限位器" in button.text()
)
limiter_manual.click()
app.processEvents()
assert "door_limiter" not in attachment_dialog.default_quantity_manual_overrides
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "门限位器"
)["quantity"] == 1

limiter_default = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
    if button.isVisible() and "门限位器" in button.text()
)
limiter_default.click()
app.processEvents()
assert "door_limiter" in attachment_dialog.default_selection_opt_outs
attachment_dialog.rebuild_table()
app.processEvents()
assert not any(item.get("item_name") == "门限位器" for item in attachment_dialog.attachments)
limiter_cancelled = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchCancelled")
    if button.isVisible() and "门限位器" in button.text()
)
limiter_cancelled.click()
app.processEvents()
assert "door_limiter" not in attachment_dialog.default_selection_opt_outs
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "门限位器"
)["quantity"] == 1
a3_quick = visible_quick_rule_button("a3_folder")
a4_quick = visible_quick_rule_button("a4_folder")
a3_quick.click()
a4_quick.click()
app.processEvents()
assert {
    item.get("item_name") for item in attachment_dialog.attachments
} >= {"A3资料盒", "A4资料盒"}
assert visible_quick_rule_button("a3_folder").objectName() == "attachmentQuickMatchSelected"
assert visible_quick_rule_button("a4_folder").objectName() == "attachmentQuickMatchSelected"
visible_quick_rule_button("a3_folder").click()
app.processEvents()
assert not any(item.get("item_name") == "A3资料盒" for item in attachment_dialog.attachments)
assert any(item.get("item_name") == "A4资料盒" for item in attachment_dialog.attachments)
visible_quick_rule_button("a4_folder").click()
app.processEvents()
assert not any(
    item.get("item_name") in {"A3资料盒", "A4资料盒"}
    for item in attachment_dialog.attachments
)
if artifact_dir is not None:
    assert attachment_dialog.grab().save(str(artifact_dir / "v3_attachment_categories.png"))

copper_row = next(
    row for row in range(attachment_dialog.table.rowCount())
    if attachment_dialog.table.item(row, attachment_dialog.COL_NAME).text() == "铜排"
)
attachment_dialog.table.item(copper_row, attachment_dialog.COL_QUANTITY).setText("3")
app.processEvents()
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "铜排"
)["quantity"] == 3
attachment_dialog.rebuild_table()
app.processEvents()
assert attachment_dialog.table.item(copper_row, attachment_dialog.COL_QUANTITY).text() == "3"
copper_manual = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchManual")
    if button.isVisible() and "铜排" in button.text()
)
assert copper_manual.text() == "人工数量  ·  铜排 · 数量：3 件", copper_manual.text()
copper_manual.click()
app.processEvents()
assert "copper_busbar" in attachment_dialog.default_selection_opt_outs
attachment_dialog.rebuild_table()
app.processEvents()
assert not any(item.get("item_name") == "铜排" for item in attachment_dialog.attachments)
copper_cancelled = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchCancelled")
    if button.isVisible() and "铜排" in button.text()
)
copper_cancelled.click()
app.processEvents()
assert "copper_busbar" not in attachment_dialog.default_selection_opt_outs
assert next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "铜排"
)["quantity"] == 1

attachment_category_button("资料盒").click()
app.processEvents()
folder_rows = [
    row for row in range(attachment_dialog.table.rowCount())
    if not attachment_dialog.table.isRowHidden(row)
]
assert len(folder_rows) == 2
a3_row = next(
    row for row in folder_rows
    if attachment_dialog.table.item(row, attachment_dialog.COL_NAME).text() == "A3资料盒"
)
a4_row = next(row for row in folder_rows if row != a3_row)
row_click_item = attachment_dialog.table.item(a3_row, attachment_dialog.COL_NAME)
assert attachment_dialog.table.item(
    a3_row, attachment_dialog.COL_CHECK
).checkState() == Qt.CheckState.Unchecked
QTest.mouseClick(
    attachment_dialog.table.viewport(),
    Qt.MouseButton.LeftButton,
    pos=attachment_dialog.table.visualItemRect(row_click_item).center(),
)
app.processEvents()
assert attachment_dialog.table.item(
    a3_row, attachment_dialog.COL_CHECK
).checkState() == Qt.CheckState.Checked
# Clicking another cell in an already selected row is additive rather than a
# toggle, so the first click of a price/quantity double-click cannot deselect it.
attachment_dialog.table.itemClicked.emit(
    attachment_dialog.table.item(a3_row, attachment_dialog.COL_PRICE)
)
assert attachment_dialog.table.item(
    a3_row, attachment_dialog.COL_CHECK
).checkState() == Qt.CheckState.Checked
assert "单击附件行可选中" in attachment_dialog.selection_hint.text()
assert attachment_dialog.table.item(a4_row, attachment_dialog.COL_CHECK).checkState() == Qt.CheckState.Unchecked
attachment_dialog.back_attachment_category()
app.processEvents()
folder_manual_cards = [
    button for button in attachment_dialog.findChildren(
        QPushButton, "attachmentManualSelection"
    )
    if button.isVisible() and "A3资料盒" in button.text()
]
assert len(folder_manual_cards) == 1
assert not any(
    button.isVisible() and "A3资料盒" in button.text()
    for button in attachment_dialog.findChildren(
        QPushButton, "attachmentQuickMatchManual"
    )
)
folder_manual_cards[0].click()
app.processEvents()
assert attachment_dialog.table.item(a4_row, attachment_dialog.COL_CHECK).checkState() == Qt.CheckState.Unchecked
visible_quick_rule_button("a4_folder").click()
app.processEvents()
assert attachment_dialog.table.item(a4_row, attachment_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked

attachment_category_button("滤网").click()
app.processEvents()
assert not attachment_dialog.table.isHidden()
assert not attachment_dialog.search_edit.isHidden()
visible_rows = [
    row
    for row in range(attachment_dialog.table.rowCount())
    if not attachment_dialog.table.isRowHidden(row)
]
assert len(visible_rows) == 1, visible_rows
app.processEvents()
assert selection_status.isVisible()
assert attachment_dialog.table.geometry().bottom() < selection_status.geometry().top(), (
    attachment_dialog.table.geometry(), selection_status.geometry()
)
for visible_widget in (
    attachment_dialog.attachment_dialog_header,
    attachment_dialog.catalog_hint,
    attachment_dialog.search_edit,
    attachment_dialog.category_breadcrumb,
    attachment_dialog.table,
    selection_status,
):
    top_left = visible_widget.mapTo(attachment_dialog, visible_widget.rect().topLeft())
    bottom_right = visible_widget.mapTo(attachment_dialog, visible_widget.rect().bottomRight())
    assert top_left.y() >= 0 and bottom_right.y() < attachment_dialog.height(), (
        visible_widget.objectName(),
        top_left,
        bottom_right,
        attachment_dialog.size(),
        visible_widget.minimumSize(),
    )
visible_source = attachment_dialog.table.item(
    visible_rows[0], attachment_dialog.COL_CHECK
).data(Qt.ItemDataRole.UserRole)
assert visible_source["model_code"] == "过滤网FU-9803A"
assert attachment_dialog.table.item(
    visible_rows[0], attachment_dialog.COL_PRICE
).text() == "15"
if artifact_dir is not None:
    assert attachment_dialog.grab().save(str(artifact_dir / "v3_attachment_leaf_table.png"))

while attachment_dialog.category_selection:
    attachment_dialog.back_attachment_category()
app.processEvents()
attachment_category_button("底座").click()
app.processEvents()
assert [button.text().splitlines()[0] for button in attachment_category_buttons()] == [
    "固定底座", "活动底座",
]
attachment_category_button("固定底座").click()
app.processEvents()
assert not attachment_dialog.table.isHidden()
visible_rows = [row for row in range(attachment_dialog.table.rowCount()) if not attachment_dialog.table.isRowHidden(row)]
assert len(visible_rows) == 1, visible_rows
assert attachment_dialog.table.item(visible_rows[0], attachment_dialog.COL_NAME).text() == "固定底座"
assert attachment_dialog.table.item(
    visible_rows[0], attachment_dialog.COL_CHECK
).checkState() == Qt.CheckState.Checked
while attachment_dialog.category_selection:
    attachment_dialog.back_attachment_category()
app.processEvents()
light_default = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
    if button.isVisible() and "灯开关" in button.text()
)
light_default.click()
attachment_dialog.accept_selection()
assert attachment_parent.attachment_default_opt_outs == {
    "installation_board", "three_row_installation_beam", "fixed_column",
    "a3_folder", "ganged_connector", "inner_door", "rain_cover",
    "ventilation_hood", "light_switch",
}, attachment_parent.attachment_default_opt_outs
assert sum(
    item.get("item_name") == "A4资料盒"
    for item in attachment_dialog.attachments
) == 1
# Reopening with a confirmed snapshot preserves that one opt-in choice without
# auto-selecting its sibling or adding a duplicate row.
reopened_dialog = attachment_dialog_class(
    [dict(item) for item in attachment_dialog.attachments],
    api_url="http://127.0.0.1:1",
    parent=attachment_parent,
    target_dimensions=(760, 960, 500),
)
reopened_dialog.catalog = [dict(item) for item in attachment_dialog.catalog]
reopened_dialog.rebuild_table()
reopened_dialog.show()
app.processEvents()
assert sum(
    item.get("item_name") == "A4资料盒"
    for item in reopened_dialog.attachments
) == 1
assert not any(item.get("item_name") == "A3资料盒" for item in reopened_dialog.attachments)
assert any(
    button.isVisible()
    and button.property("attachmentQuickRule") == "a4_folder"
    and button.objectName() == "attachmentQuickMatchSelected"
    for button in reopened_dialog.findChildren(QPushButton)
)
reopened_dialog.close()
assert attachment_parent.attachment_default_quantity_overrides == set()
attachment_parent.close()

plain_parent = QWidget()
plain_parent.quote_spec_edit = QLineEdit(plain_parent)
plain_parent.quote_spec_edit.setText("760*500*960")
plain_dialog = attachment_dialog_class(
    [],
    api_url="http://127.0.0.1:1",
    parent=plain_parent,
    target_dimensions=(760, 960, 500),
)
plain_dialog.catalog = [dict(item) for item in attachment_dialog.catalog]
assert plain_dialog.prepare_default_selections() == 5
plain_dialog.rebuild_table()
plain_dialog.show()
app.processEvents()
plain_quick_labels = plain_dialog.findChildren(QPushButton, "attachmentQuickMatch")
assert any(label.text() == "快速匹配  ·  无需底座" for label in plain_quick_labels)
assert any(label.text() == "快速匹配  ·  仅 JP 默认匹配" for label in plain_quick_labels)
assert sum(
    plain_dialog.table.item(row, plain_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked
    for row in range(plain_dialog.table.rowCount())
) == 5
plain_dialog.close()
plain_parent.close()
attachment_dialog_class.load_catalog = original_attachment_load

# Exercise the complete current desktop stack. Do not disable Scheme2 or the
# quotation-scheme centre to satisfy retired V3 whole-page assertions.
import quote_scheme_center
import scheme2_ui

assert namespace["MainWindow"]._scheme2_ui_installed
assert namespace["MainWindow"]._quote_scheme_center_installed

original_scheme_worker_run = quote_scheme_center.QuoteSchemeWorker.run
quote_scheme_center.QuoteSchemeWorker.run = lambda self: self.succeeded.emit(
    {"page": 1, "page_size": 20, "total": 0, "items": []}
)
namespace["ApiWorker"].run = lambda self: self.failed.emit("offline test transport")
window = namespace["MainWindow"]()
try:
    window.show()
    app.processEvents()
    assert [button.text() for button in window.nav_buttons] == [
        "选型配置", "成本计算", "报价单", "报价方案",
    ]
    assert window.nav_routes == (
        (1, "选型配置", "", None), (3, "成本计算", "", None),
        (2, "报价单", "", None), (6, "报价方案", "", None),
    )
    pages = {
        1: "scheme2OptionPage", 3: "scheme2CostPage",
        2: "scheme2QuotePage", 6: "quoteSchemeCenterPage",
    }
    for route, object_name in pages.items():
        assert window.stack.widget(route).objectName() == object_name
    assert window.scheme2_company.isEnabled()
    assert window.scheme2_quote_preview.columnCount() == 8
    assert not window.scheme2_quote_print.isEnabled()
    assert not window.scheme2_quote_export.isEnabled()
    assert [
        window.summary_table.horizontalHeaderItem(column).text()
        for column in range(window.summary_table.columnCount())
    ] == [
        "序号", "名称", "产品", "尺寸", "数量", "已选附件", "附件面价", "面价",
        "材料差价", "折扣系数", "报价", "报价总价", "成本单价", "材料成本",
        "辅材成本", "人工成本", "附件成本", "喷涂费用", "管理费用", "运费",
        "成本总价", "毛利率", "自制件重量", "成本明细",
    ]
    assert window.quote_scheme_nav_button is window.nav_buttons[-1]
    assert window.quote_scheme_operator_name is not window.quote_scheme_filters["creator"]
    assert window.findChild(QLabel, "quoteSchemeServerNotice").text() == "● 数据保存于服务器"
    assert window.quote_scheme_table.columnCount() == 9
    # Superseded widgets may remain as internal core dependencies, but must
    # never reappear in the visible navigation or active quotation pages.
    assert window.attachment_list.isHidden()
    assert window.attachment_summary_table.isHidden()
    service = window.scheme2_service_status
    assert service.parentWidget() is window.scheme2_nav
    for width, height in ((1024, 700), (1280, 800), (1536, 900)):
        window.resize(width, height)
        for route, object_name in pages.items():
            window.show_section(route)
            app.processEvents()
            page = window.stack.currentWidget()
            assert page.objectName() == object_name
            assert page.isVisible()
            assert page.width() > 400 and page.height() > 300
            assert sum(button.isChecked() for button in window.nav_buttons) == 1
            assert service.y() > window.nav_buttons[-1].y()
            if route == 3:
                assert window.summary_table.viewport().width() > 400
                assert window.summary_table.viewport().height() > 100
            if route == 6:
                deadline = time.monotonic() + 3
                while window._quote_scheme_workers and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(5)
                assert not window._quote_scheme_workers
                assert window.quote_scheme_table.rowCount() == 0
                assert window.quote_scheme_table.viewport().width() > 400
            if artifact_dir is not None:
                assert window.grab().save(str(artifact_dir / f"current_{route}_{width}x{height}.png"))
finally:
    window.close()
    app.processEvents()
    quote_scheme_center.QuoteSchemeWorker.run = original_scheme_worker_run

print("CURRENT_CLIENT_LAYOUT=PASS")
print("ATTACHMENT_BROWSER_AND_CURRENT_NAVIGATION=PASS")
