"""Runtime contract check for the source-controlled V3 layout overlay.

The verified client core remains an external build artifact.  Point
``AI_QUOTE_V3_CORE_ROOT`` at its ``_internal/v3_core`` directory and run this
script with the Python 3.12/PySide6 environment used to build the client.
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

from PySide6.QtCore import QRect, Qt  # noqa: E402
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

# The attachment picker is fixed after construction, but caps its logical
# dimensions to the active desktop at common Windows scaling levels.
for logical_size, expected in {
    (1092, 614): (900, 582),   # 1366x768 at 125% (representative logical area)
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
        "item_name": "三排纵梁",
        "model_code": "BEAM-3",
        "price": 25,
        "category_level1": "三排纵梁",
    },
    {
        "item_name": "JK安装板",
        "model_code": "JK安装板",
        "price": 80,
        "category_level1": "安装板",
        "category_level2": "JK安装板",
        "width_mm": 760,
        "height_mm": 960,
        "depth_mm": 500,
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
        "category_level1": "文件夹",
    },
    {
        "attachment_price_id": 9,
        "item_name": "A4资料盒",
        "price": 30,
        "category_level1": "文件夹",
    },
    {
        "item_name": "过滤网FU-9803A",
        "model_code": "过滤网FU-9803A",
        "variant": "7035色",
        "price": 15,
        "category_level1": "风机滤网",
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
assert attachment_dialog.prepare_default_selections() == 8
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
attachment_dialog.resize(900, 680)
attachment_dialog.show()
app.processEvents()
expected_attachment_size = layout_refresh._attachment_dialog_target_size(attachment_dialog)
assert (attachment_dialog.width(), attachment_dialog.height()) == expected_attachment_size
assert attachment_dialog.width() <= layout_refresh.ATTACHMENT_DIALOG_TARGET_WIDTH
assert attachment_dialog.height() <= layout_refresh.ATTACHMENT_DIALOG_TARGET_HEIGHT
assert (
    attachment_dialog.minimumWidth()
    == attachment_dialog.maximumWidth()
    == expected_attachment_size[0]
)
assert (
    attachment_dialog.minimumHeight()
    == attachment_dialog.maximumHeight()
    == expected_attachment_size[1]
)
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
        if button.text().splitlines()[0] == label
    )


level1_buttons = attachment_category_buttons()
assert [button.text().splitlines()[0] for button in level1_buttons] == [
    "底座", "侧板", "三排纵梁", "安装板", "灯开关", "文件夹", "风机滤网",
    "门限位器", "门加强筋", "配置变形", "门变形", "接地线", "铜排", "未来分类",
]
assert all(button.parentWidget().minimumHeight() >= 118 for button in level1_buttons)
positions = [
    attachment_dialog.category_grid.getItemPosition(
        attachment_dialog.category_grid.indexOf(button.parentWidget())
    )[:2]
    for button in level1_buttons
]
attachment_columns = layout_refresh._attachment_category_column_count(attachment_dialog)
expected_positions = [
    (index // attachment_columns, index % attachment_columns)
    for index in range(min(len(level1_buttons), attachment_columns + 1))
]
assert positions[:len(expected_positions)] == expected_positions, positions
row_count = max(row for row, _column in positions) + 1
assert attachment_dialog.category_scroll_content.minimumHeight() >= (
    row_count * 118
    + max(0, row_count - 1) * attachment_dialog.category_grid.verticalSpacing()
)
assert attachment_dialog.table.isHidden()
quick_match_buttons = attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
assert len(quick_match_buttons) == 8
assert any(button.text() == "默认已选择\n固定 · 高 100 mm" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\nA4资料盒" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n门加强筋 · 数量：1 个" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n红绿线" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n门限位器 · 数量：1 个" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n铜排 · 默认数量：1 件" for button in quick_match_buttons)

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
        "category_level1": "风机滤网",
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
        if button.isVisible() and button.text().splitlines()[0] == label
    )


visible_dialog_category_button(door_dialog, "门变形").click()
app.processEvents()
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
visible_dialog_category_button(door_dialog, "风机滤网").click()
app.processEvents()
visible_dialog_category_button(door_dialog, "风机").click()
app.processEvents()
visible_dialog_category_button(door_dialog, "三级风机附件").click()
app.processEvents()
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

# An installation board selected through category browsing is summarized back
# on the first-level card.  Its circular sign toggle keeps the original price
# positive in metadata and stores subtraction separately.
attachment_category_button("安装板").click()
app.processEvents()
attachment_category_button("JK安装板").click()
app.processEvents()
board_row = next(
    row for row in range(attachment_dialog.table.rowCount())
    if attachment_dialog.table.item(row, attachment_dialog.COL_NAME).text() == "JK安装板"
)
attachment_dialog.table.item(board_row, attachment_dialog.COL_CHECK).setCheckState(Qt.CheckState.Checked)
app.processEvents()
while attachment_dialog.category_selection:
    attachment_dialog.back_attachment_category()
app.processEvents()
board_summary = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentManualSelection")
    if button.isVisible() and "JK安装板" in button.text()
)
assert board_summary.text().startswith("人工已选择\nJK安装板\n")
board_sign = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentPriceSignPositive")
    if button.isVisible()
)
assert board_sign.text() == "+"
board_sign.click()
app.processEvents()
negative_sign = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentPriceSignNegative")
    if button.isVisible()
)
assert negative_sign.text() == "−"
board_source = attachment_dialog.table.item(
    board_row, attachment_dialog.COL_CHECK
).data(Qt.ItemDataRole.UserRole)
assert board_source["attachment_price_sign"] == -1
assert attachment_dialog.table.item(board_row, attachment_dialog.COL_PRICE).text() == "-80"
selected_board = next(
    item for item in attachment_dialog.attachments if item.get("item_name") == "JK安装板"
)
fresh_board = next(
    item for item in attachment_dialog.collect_attachments(False)
    if item.get("item_name") == "JK安装板"
)
assert fresh_board["attachment_price_sign"] == -1, fresh_board
assert selected_board["attachment_price_sign"] == -1, attachment_dialog.attachments
assert selected_board["matched_price"] == 80

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
folder_default = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
    if button.isVisible() and "A4资料盒" in button.text()
)
folder_default.click()
app.processEvents()
assert "a4_folder" in attachment_dialog.default_selection_opt_outs
attachment_dialog.rebuild_table()
app.processEvents()
assert len([
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
    if button.isVisible()
]) == 7
folder_cancelled = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchCancelled")
    if button.isVisible() and "A4资料盒" in button.text()
)
if artifact_dir is not None:
    assert attachment_dialog.grab().save(str(artifact_dir / "v3_attachment_default_cancelled.png"))
folder_cancelled.click()
app.processEvents()
assert "a4_folder" not in attachment_dialog.default_selection_opt_outs
assert len([
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
    if button.isVisible()
]) == 8
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
assert copper_manual.text() == "人工数量\n铜排 · 数量：3 件", copper_manual.text()
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

attachment_category_button("文件夹").click()
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
attachment_dialog.table.item(a3_row, attachment_dialog.COL_CHECK).setCheckState(Qt.CheckState.Checked)
app.processEvents()
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
folder_cancelled = next(
    button for button in attachment_dialog.findChildren(
        QPushButton, "attachmentQuickMatchCancelled"
    )
    if button.isVisible() and "A4资料盒" in button.text()
)
folder_cancelled.click()
app.processEvents()
assert attachment_dialog.table.item(a4_row, attachment_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked

attachment_category_button("风机滤网").click()
app.processEvents()
assert [button.text().splitlines()[0] for button in attachment_category_buttons()] == ["过滤网"]
attachment_category_button("过滤网").click()
app.processEvents()
assert [button.text().splitlines()[0] for button in attachment_category_buttons()] == [
    "过滤网FU-9803A"
]
attachment_category_button("过滤网FU-9803A").click()
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
assert attachment_parent.attachment_default_opt_outs == {"light_switch"}
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
assert plain_dialog.prepare_default_selections() == 6
plain_dialog.rebuild_table()
plain_dialog.show()
app.processEvents()
plain_quick_labels = plain_dialog.findChildren(QPushButton, "attachmentQuickMatch")
assert any(label.text() == "快速匹配\n无需底座" for label in plain_quick_labels)
assert any(label.text() == "快速匹配\n仅 JP 默认匹配" for label in plain_quick_labels)
assert sum(
    plain_dialog.table.item(row, plain_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked
    for row in range(plain_dialog.table.rowCount())
) == 6
plain_dialog.close()
plain_parent.close()
attachment_dialog_class.load_catalog = original_attachment_load

window = namespace["MainWindow"]()
window.resize(1519, 987)
window.show()
window.show_section(1)
app.processEvents()
layout_refresh._position_quote_action_dock(window)
app.processEvents()
assert window.freight_spin.value() == 0
assert window.freight_spin.toolTip().startswith("填写每台柜体或每套并柜的运费")
assert len([
    label for label in window.findChildren(QLabel)
    if label.text().strip() == "运费"
]) >= 3
assert window.attachment_list.font().pointSize() >= 10
assert window.attachment_list.maximumHeight() == 116
assert window.freight_spin.parentWidget() is window.freight_field_block
assert window.freight_field_block.objectName() == "fieldBlock"
assert window.freight_label.buddy() is window.freight_spin
for name in (
    "product_combo", "model_edit", "width_spin", "depth_spin", "height_spin",
    "quote_spec_edit", "material_combo", "coating_combo", "quote_date",
    "single_door_combo", "double_door_combo", "quantity_spin", "freight_spin",
):
    control = getattr(window, name)
    assert control.minimumHeight() >= layout_refresh.UI_CONTROL_HEIGHT, (name, control.minimumHeight())
    assert control.accessibleName(), name

# The sticky action dock must occupy a real layout row below QScrollArea, not
# float over its native viewport where Windows can intercept manual clicks.
assert window.centralWidget() is window.quote_action_dock_host
assert window.quote_action_dock.parentWidget() is window.quote_action_dock_host
assert window.quote_action_dock_host.layout().indexOf(window.quote_action_dock) >= 0
button_center = window.calculate_button.mapToGlobal(
    window.calculate_button.rect().center()
)
hit_widget = QApplication.widgetAt(button_center)
assert window.calculate_button.isVisible()
assert window.quote_action_dock.rect().contains(
    window.calculate_button.mapTo(window.quote_action_dock, window.calculate_button.rect().center())
)
# The offscreen Qt platform does not implement native widgetAt(), but on a
# desktop platform the center of the visible action must resolve to the
# button itself.
if hit_widget is not None:
    assert hit_widget is window.calculate_button, (
        hit_widget.objectName(),
        window.calculate_button.geometry(),
        window.quote_action_dock.geometry(),
    )

# The visible primary action must enter the ganged-aware calculation path.
# Mock only the transport boundary so parsing, payload generation, QThread
# lifetime, aggregation and MainWindow rendering all execute as production.
window.product_catalog = {
    "JP": {
        "codes": {"SINGLE": "JP_SINGLE", "DOUBLE": "JP_DOUBLE"},
        "method": "formula",
    }
}
window.quote_catalog_state = "ready"
window.product_combo.clear()
window.product_combo.addItem("JP", "JP")
window.formula_calculator.calculate = (
    lambda _code, width, height, depth, _single, _double: (
        round(width * height * depth / 10_000_000, 1),
        round((width + height + depth) / 1000, 1),
    )
)
assert layout_refresh._missing_ganged_formula_product_codes(window) == []
window.api_url.setText("https://quote.test/api/quotes/calculate-dual")
window.attachments = []
window.quantity_spin.setValue(2)
window.freight_spin.setValue(50)
window.quote_spec_edit.setText("（600+900）*300*1800")
assert layout_refresh._sync_ganged_specification(
    window, "（600+900）*300*1800"
)
app.processEvents()
window.ganged_cabinets = [
    {
        "width_mm": 600,
        "depth_mm": 300,
        "height_mm": 1800,
        "base_height_mm": None,
        "single_door_count": 1,
        "double_door_count": 0,
    },
    {
        "width_mm": 900,
        "depth_mm": 300,
        "height_mm": 1800,
        "base_height_mm": None,
        "single_door_count": 1,
        "double_door_count": 0,
    },
]
window.ganged_cabinet_count = 2
window.ganged_cabinet_specification = "（600+900）*300*1800"
layout_refresh._render_ganged_cabinet_table(window)
assert window.ganged_cabinet_table.item(0, 0).text() == "1"
assert window.ganged_cabinet_table.cellWidget(0, 0) is None
assert layout_refresh._missing_ganged_formula_product_codes(window) == ["JP_SINGLE"]

working_formula_calculate = window.formula_calculator.calculate
window.formula_calculator.calculate = lambda *_args: None
try:
    layout_refresh._build_ganged_quote_payloads(window)
except ValueError as exc:
    assert "第 1 个子柜的公式重量和面积尚未生成" in str(exc)
else:
    raise AssertionError("missing ganged formula metrics must block the request")
window.formula_calculator.calculate = working_formula_calculate

class MockHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


child_results = [
    {
        "formula_cost": {
            "material_cost": 100,
            "auxiliary_cost": 20,
            "labor_cost": 30,
            "spray_cost": 40,
            "management_fee": 3.9,
            "attachment_fee": 0,
            "total_cost": 193.9,
            "product_area_m2": 2.7,
        },
        "quick_quote": {
            "base_price": 1000,
            "attachment_fee": 0,
            "total_cost": 1000,
            "dimension_distance": 0,
            "matched_experience": {"reference_width_mm": 600, "reference_height_mm": 1800, "reference_depth_mm": 300},
        },
        "risk_flags": [],
    },
    {
        "formula_cost": {
            "material_cost": 150,
            "auxiliary_cost": 25,
            "labor_cost": 35,
            "spray_cost": 45,
            "management_fee": 4.55,
            "attachment_fee": 0,
            "total_cost": 259.55,
            "product_area_m2": 3.0,
        },
        "quick_quote": {
            "base_price": 1500,
            "attachment_fee": 0,
            "total_cost": 1500,
            "dimension_distance": 0,
            "matched_experience": {"reference_width_mm": 900, "reference_height_mm": 1800, "reference_depth_mm": 300},
        },
        "risk_flags": [],
    },
]
recorded_payloads = []
template_requests = []
original_urlopen = layout_refresh.urllib.request.urlopen

def successful_urlopen(request, timeout=0):
    del timeout
    if request.full_url.endswith("/api/quotes/formula-template"):
        template_request = json.loads(request.data.decode("utf-8"))
        template_requests.append(template_request)
        time.sleep(0.3)
        return MockHttpResponse({
            "template": {
                "template_code": template_request["product_code"],
                "option_cells": {"defaults": {}},
                "rules": [],
            }
        })
    recorded_payloads.append(json.loads(request.data.decode("utf-8")))
    time.sleep(0.3)
    return MockHttpResponse(child_results[len(recorded_payloads) - 1])


layout_refresh.urllib.request.urlopen = successful_urlopen
window.update_quote_readiness()
assert window.calculate_button.isEnabled()
app.processEvents()
window.calculate_button.click()
app.processEvents()
assert window.ganged_template_worker is not None
assert window.ganged_template_worker.isRunning()
assert not window.calculate_button.isEnabled()
assert "正在读取 1 个并柜公式模板" in window.findChild(
    QLabel, "quoteResultState"
).text()
deadline = time.monotonic() + 5
while (
    (
        getattr(window, "ganged_template_worker", None) is not None
        or getattr(window, "worker", None) is not None
        or len(recorded_payloads) < 2
    )
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
assert window.ganged_template_worker is None
assert window.worker is None
assert window.calculate_button.isEnabled()
assert window.calculate_button.text() == "计算双报价"
assert template_requests == [{"product_code": "JP_SINGLE"}]
assert layout_refresh._missing_ganged_formula_product_codes(window) == []
assert len(recorded_payloads) == 2
assert [payload["model_code"] for payload in recorded_payloads] == [
    "600×300×1800", "900×300×1800",
]
assert [payload["product_code"] for payload in recorded_payloads] == [
    "JP_SINGLE", "JP_SINGLE",
]
assert [payload["attachments"] for payload in recorded_payloads] == [[], []]
assert all("freight_fee" not in payload for payload in recorded_payloads)
assert [payload["base_material_weight_kg"] for payload in recorded_payloads] == [
    32.4, 48.6,
]
assert [payload["product_area_m2"] for payload in recorded_payloads] == [
    2.7, 3.0,
]
assert window.current_result is not None, (
    window.findChild(QLabel, "quoteResultState").text(),
    window.risk_label.text(),
    len(recorded_payloads),
)
assert window.weight_edit.text() == "81.0"
assert window.area_edit.text() == "5.7"
assert window.current_result["formula"]["material_cost"] == 250
assert window.current_result["formula"]["spray_cost"] == 85
assert window.current_result["formula"]["product_area_m2"] == 5.7
assert abs(window.current_result["formula"]["total_cost"] - 453.45) < 1e-9
assert window.current_result["quick"]["total_cost"] == 2500, window.current_result
assert window.formula_labels["freight"].text() == "50.00 元"
assert window.quick_labels["freight"].text() == "50.00 元"
assert window.formula_labels["total"].text() == "503.45 元"
assert window.quick_labels["total"].text() == "2,550.00 元"
assert len(window.current_result["quick"]["matched_experience"]["items"]) == 2
assert "已合并 2 个子柜" in window.findChild(QLabel, "quoteResultState").text()
assert window.pending_quote_signature == window.quote_input_signature()
assert window.pending_quote_signature[-1][0] == "ganged"
formula_order = layout_refresh._formula_order_line_breakdown({
    "formula": window.current_result["formula"],
    "attachments": [],
    "quantity": 2,
    "formula_discount": 1,
    "ganged_cabinet_count": 2,
    "freight_fee": 50,
})
quick_order = layout_refresh.quick_order_line_breakdown(
    window.current_result["quick"], [], 1, 2, 2, 50,
)
assert formula_order["freight_total"] == 100
assert abs(formula_order["line_total"] - 1006.9) < 1e-9
assert quick_order["freight_total"] == 100
assert quick_order["line_total"] == 5100
door_strip = {
    "item_name": "门安装条",
    "category_level1": "门安装条",
    "quantity": 1,
    "unit_price": 20,
}
door_strip_formula_order = layout_refresh._formula_order_line_breakdown({
    "formula": {"attachment_fee": 20, "total_cost": 1020},
    "attachments": [door_strip],
    "quantity": 3,
    "formula_discount": 0.8,
})
assert door_strip_formula_order["discounted_attachment_total"] == 0
assert door_strip_formula_order["original_price_attachment_total"] == 60
assert door_strip_formula_order["line_total"] == 2460
if artifact_dir is not None:
    window.show_section(1)
    app.processEvents()
    assert window.grab().save(str(artifact_dir / "v3_ganged_quote_success.png"))
window.freight_spin.setValue(0)

# A failed request must be explicit and must restore both button and worker.
def failed_urlopen(_request, timeout=0):
    del timeout
    raise OSError("simulated network failure")


layout_refresh.urllib.request.urlopen = failed_urlopen
window.calculate_button.click()
deadline = time.monotonic() + 5
while window.worker is not None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert window.worker is None
assert window.calculate_button.isEnabled()
assert "并柜报价失败" in window.findChild(QLabel, "quoteResultState").text()
assert "simulated network failure" in window.findChild(
    QLabel, "quoteResultState"
).text()
if artifact_dir is not None:
    app.processEvents()
    assert window.grab().save(str(artifact_dir / "v3_ganged_quote_failure.png"))

# Ordinary one-cabinet calculation still falls through to the recovered path.
ordinary_requests = []

def ordinary_urlopen(request, timeout=0):
    del timeout
    ordinary_requests.append(json.loads(request.data.decode("utf-8")))
    return MockHttpResponse(child_results[0])


layout_refresh.urllib.request.urlopen = ordinary_urlopen
window.ganged_cabinets = []
window.ganged_cabinet_count = 1
window.product_catalog["JP"]["method"] = "manual"
window.set_door_counts(1, 0)
window.width_spin.setValue(600)
window.depth_spin.setValue(300)
window.height_spin.setValue(1800)
window.model_edit.setText("JP-600")
window.quote_spec_edit.setText("600*300*1800")
window.weight_edit.setText("32.4")
window.area_edit.setText("2.7")
window.calculate_button.setEnabled(True)
modal_calls = []
original_message_warning = QMessageBox.warning
original_message_information = QMessageBox.information
QMessageBox.warning = lambda _parent, title, message, *_args: modal_calls.append((title, message))
QMessageBox.information = lambda _parent, title, message, *_args: modal_calls.append((title, message))
window.calculate_button.click()
deadline = time.monotonic() + 5
while (
    getattr(window, "worker", None) is not None
    and window.worker.isRunning()
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
QMessageBox.warning = original_message_warning
QMessageBox.information = original_message_information
assert not modal_calls, modal_calls
assert len(ordinary_requests) == 1
assert ordinary_requests[0]["model_code"] == "JP-600"
assert window.current_result["quick"]["total_cost"] == 1000

# A formula quote clicked after a TLS/template failure must retry in the
# background and automatically resume the pending calculation.  It must not
# show the old "please click again later" modal.
window.product_catalog["JP"]["method"] = "formula"
window.weight_edit.clear()
window.area_edit.clear()
window.template_worker = None
window.current_result = None
formula_template_attempts = []
resumed_quote_requests = []
original_formula_load_template = window.formula_calculator.load_template
original_formula_calculate = window.formula_calculator.calculate
original_retry_delays = layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS
original_debounce_ms = layout_refresh.FORMULA_TEMPLATE_DEBOUNCE_MS
window.formula_calculator.load_template = lambda _payload: None
window.formula_calculator.calculate = lambda *_args: (40.7, 1.9)
layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS = (1, 1)
layout_refresh.FORMULA_TEMPLATE_DEBOUNCE_MS = 1

def transient_template_then_quote(request, timeout=0):
    assert timeout in (30, layout_refresh.FORMULA_TEMPLATE_REQUEST_TIMEOUT_SECONDS)
    if request.full_url.endswith("/api/quotes/formula-template"):
        formula_template_attempts.append(timeout)
        if len(formula_template_attempts) == 1:
            raise TimeoutError("The handshake operation timed out")
        return MockHttpResponse({
            "template": {
                "template_code": "JP_SINGLE",
                "option_cells": {"defaults": {}},
                "rules": [],
            }
        })
    resumed_quote_requests.append(json.loads(request.data.decode("utf-8")))
    return MockHttpResponse(child_results[0])


layout_refresh.urllib.request.urlopen = transient_template_then_quote
window.refresh_formula_inputs()
app.processEvents()
assert window.calculate_button.isEnabled()
assert any(
    text in window.calculate_button.text()
    for text in ("准备读取公式模板", "模板读取中，可点击计算")
), window.calculate_button.text()
window.calculate_button.click()
app.processEvents()
assert window._pending_formula_calculation
assert not window.calculate_button.isEnabled()
assert "读取完成后将自动继续计算" in window.findChild(
    QLabel, "quoteResultState"
).text()
deadline = time.monotonic() + 5
while (
    (
        getattr(window, "_formula_template_debounce_timer", None).isActive()
        or
        getattr(window, "template_worker", None) is not None
        or getattr(window, "worker", None) is not None
        or not resumed_quote_requests
    )
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
assert len(formula_template_attempts) == 2, formula_template_attempts
assert len(resumed_quote_requests) == 1, resumed_quote_requests
assert resumed_quote_requests[0]["base_material_weight_kg"] == 40.7
assert resumed_quote_requests[0]["product_area_m2"] == 1.9
assert not modal_calls, modal_calls
assert window.current_result is not None
assert window.current_result["quick"]["total_cost"] == 1000

# Exhausting all retries must restore the action and show an explicit error.
failed_template_attempts = []

def always_timeout_template(_request, timeout=0):
    assert timeout == layout_refresh.FORMULA_TEMPLATE_REQUEST_TIMEOUT_SECONDS
    failed_template_attempts.append(timeout)
    raise TimeoutError("The handshake operation timed out")


layout_refresh.urllib.request.urlopen = always_timeout_template
window.weight_edit.clear()
window.area_edit.clear()
window.calculate()
deadline = time.monotonic() + 5
while (
    (
        getattr(window, "_formula_template_debounce_timer", None).isActive()
        or getattr(window, "template_worker", None) is not None
    )
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
assert len(failed_template_attempts) == 3, failed_template_attempts
assert window.calculate_button.isEnabled()
assert "已自动尝试 3 次" in window.risk_label.text(), window.risk_label.text()
assert "handshake operation timed out" in window.risk_label.text()

# Rapid relevant-input refreshes are collapsed into one template request.
debounced_template_requests = []

def successful_debounced_template(request, timeout=0):
    assert timeout == layout_refresh.FORMULA_TEMPLATE_REQUEST_TIMEOUT_SECONDS
    debounced_template_requests.append(request.full_url)
    return MockHttpResponse({
        "template": {
            "template_code": "JP_SINGLE",
            "option_cells": {"defaults": {}},
            "rules": [],
        }
    })


layout_refresh.urllib.request.urlopen = successful_debounced_template
window.refresh_formula_inputs()
window.refresh_formula_inputs()
window.refresh_formula_inputs()
assert window.calculate_button.isEnabled()
deadline = time.monotonic() + 5
while (
    (
        getattr(window, "_formula_template_debounce_timer", None).isActive()
        or getattr(window, "template_worker", None) is not None
    )
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
assert len(debounced_template_requests) == 1, debounced_template_requests
window.formula_calculator.load_template = original_formula_load_template
window.formula_calculator.calculate = original_formula_calculate
layout_refresh.FORMULA_TEMPLATE_RETRY_DELAYS_MS = original_retry_delays
layout_refresh.FORMULA_TEMPLATE_DEBOUNCE_MS = original_debounce_ms
window.product_catalog["JP"]["method"] = "manual"
layout_refresh.urllib.request.urlopen = original_urlopen

before_attachment_change = [{"item_name": "附件 A", "quantity": 1, "unit_price": 10}]
window.attachments = [dict(before_attachment_change[0])]
window.current_result = {
    "formula": {"total_cost": 100},
    "quick": {"total_cost": 120},
}
window.attachments = []
assert layout_refresh._invalidate_quote_after_attachment_change(
    window, before_attachment_change
)
assert window.current_result is None
assert "请重新计算双报价" in window.findChild(QLabel, "quoteResultState").text()

window.attachments = [{
    "item_name": "门限位器", "category_level1": "门限位器",
    "quantity": 1, "unit_price": 25,
}]
window.quantity_spin.setValue(1)
window.set_door_counts(1, 0)
ganged_specification = "(600+1800) *200* (2000+200)"
window.quote_spec_edit.setText(ganged_specification)
window.quote_spec_edit.textEdited.emit(ganged_specification)
app.processEvents()
assert window.ganged_cabinet_table.rowCount() == 2
assert [
    window.ganged_cabinet_table.item(row, 1).text() for row in range(2)
] == ["600×200×（2000+200）", "1800×200×（2000+200）"]
assert not window.ganged_cabinet_panel.isHidden()
ganged_door_rows = [
    (
        window.ganged_cabinet_table.cellWidget(row, 2).currentData(),
        window.ganged_cabinet_table.cellWidget(row, 3).currentData(),
    )
    for row in range(2)
]
assert ganged_door_rows == [(1, 0), (1, 0)], ganged_door_rows
assert "最终数量 2" in window.attachment_list.item(0).text(), window.attachment_list.item(0).text()
plain_specification = "1000*600*1800"
window.quote_spec_edit.setText(plain_specification)
window.quote_spec_edit.textEdited.emit(plain_specification)
app.processEvents()
assert window.ganged_cabinet_table.rowCount() == 0
assert window.ganged_cabinet_panel.isHidden()

window.attachments = [{
    "item_name": "安装板", "quantity": 1, "matched_price": 100,
    "attachment_price_sign": -1,
}]
window.update_attachment_view()
assert "-100.00 元" in window.attachment_list.item(0).text()

assert window.stack.count() == 4
nav = window.findChild(QFrame, "navPanel")
assert nav is not None and nav.width() == 168

# The recovered client must display and summarize the selective quick discount,
# not the former blanket total_cost × discount result.
window.attachments = [
    {"item_name": "固定底座", "quantity": 1, "unit_price": 100},
    {"item_name": "内门", "quantity": 1, "unit_price": 200},
    {"item_name": "风机", "quantity": 1, "unit_price": 80},
    {"item_name": "接地线", "quantity": 2, "unit_price": 6},
]
window._formula_base_result = {
    "material_cost": 100,
    "auxiliary_cost": 100,
    "labor_cost": 100,
    "attachment_fee": 392,
    "spray_cost": 100,
    "management_fee": 13,
    "total_cost": 805,
}
window.current_result = {
    "formula": dict(window._formula_base_result),
    "quick": {"attachment_fee": 392, "total_cost": 4406.29},
}
window.quick_discount.setValue(0.95)
window.refresh_discounted_totals()
assert "4,190.58" in window.quick_labels["total"].text(), window.quick_labels["total"].text()

window.draft_items = [{
    "name": "折扣规则测试柜",
    "model_code": "MODEL-QUICK-DISCOUNT",
    "specification": "MODEL-QUICK-DISCOUNT",
    "width_mm": 1000,
    "height_mm": 1800,
    "depth_mm": 600,
    "material_code": "SECC",
    "quantity": 2,
    "freight_fee": 50,
    "attachments": [dict(item) for item in window.attachments],
    "formula": dict(window._formula_base_result),
    "formula_discount": 1,
    "quick": {"attachment_fee": 392, "total_cost": 4406.29},
    "quick_discount": 0.95,
    "notes": "选择性折扣测试",
}]
window.refresh_summary()
assert window.summary_table.item(0, 2).text() == "MODEL-QUICK-DISCOUNT", [
    window.summary_table.item(0, column).text()
    if window.summary_table.item(0, column) is not None else None
    for column in range(window.summary_table.columnCount())
]
quick_price_columns = [
    column
    for column in range(window.summary_table.columnCount())
    if window.summary_table.horizontalHeaderItem(column) is not None
    and "快速" in window.summary_table.horizontalHeaderItem(column).text()
    and "折扣" not in window.summary_table.horizontalHeaderItem(column).text()
]
assert quick_price_columns, [
    window.summary_table.horizontalHeaderItem(column).text()
    for column in range(window.summary_table.columnCount())
]
assert window.summary_table.item(0, quick_price_columns[0]).text() == "4,200.58", (
    window.summary_table.item(0, quick_price_columns[0]).text()
)
assert "8,401.15" in window.summary_quick_total.text(), window.summary_quick_total.text()
window.draft_items = []
window.refresh_summary()

style = window.styleSheet()
for token in (
    layout_refresh.STEEL_CANVAS,
    layout_refresh.GRAPHITE,
    layout_refresh.BLUEPRINT,
    layout_refresh.INSPECTION_GREEN,
    layout_refresh.WARNING_AMBER,
):
    assert token in style, token

window.stack.setCurrentIndex(0)
app.processEvents()
recognition_page = window.stack.widget(0)
workbench = recognition_page.findChild(QSplitter, "workbenchSplitter")
assert workbench is not None and workbench.count() == 3
left, center, right = workbench.sizes()
assert 228 <= left <= 264, workbench.sizes()
assert center >= 520, workbench.sizes()
assert 348 <= right <= 420, workbench.sizes()

candidate_table = recognition_page.findChild(QTableWidget, "candidateTable")
assert candidate_table is not None
candidate_actions = buttons_with_text(
    recognition_page,
    {"复核类型", "新增拆分项", "合并", "排除"},
)
assert len(candidate_actions) == 4
assert all(not action.isEnabled() for action in candidate_actions)
candidate_table.setRowCount(1)
candidate_table.setItem(0, 0, QTableWidgetItem("候选 1"))
candidate_table.selectRow(0)
app.processEvents()
assert all(action.isEnabled() for action in candidate_actions)

window.stack.setCurrentIndex(1)
app.processEvents()
quote_page = window.stack.widget(1)
quote_workspace = quote_page.findChild(QSplitter, "quoteWorkspace")
assert quote_workspace is not None and quote_workspace.count() == 2
quote_left, quote_right = quote_workspace.sizes()
assert quote_workspace.orientation() == Qt.Orientation.Horizontal
assert quote_workspace.property("responsiveMode") == "wide"
assert quote_left >= 620, quote_workspace.sizes()
assert quote_right >= 560, quote_workspace.sizes()
assert quote_workspace.widget(1).maximumWidth() == layout_refresh.WIDGET_MAX
assert window.findChild(QAbstractButton, "primaryQuoteAction").accessibleName() == "计算双报价"

main_scroll = window.findChild(QScrollArea, "mainScroll")
quote_dock = window.findChild(QFrame, "quoteActionDock")
assert main_scroll is not None
assert main_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
assert main_scroll.horizontalScrollBar().maximum() == 0
assert quote_dock is not None and quote_dock.isVisible()
assert quote_dock.parentWidget() is window.quote_action_dock_host
assert main_scroll.viewportMargins().bottom() == 0
main_scroll_bottom = main_scroll.geometry().bottom()
assert quote_dock.geometry().top() >= main_scroll_bottom
assert window.findChild(QAbstractButton, "secondaryQuoteAction").parentWidget() is quote_dock
assert window.findChild(QAbstractButton, "quietQuoteAction").parentWidget() is quote_dock

# A compact action dock hides only the descriptive label, not any action, and
# its minimum widths fit inside the available logical width.
layout_refresh._configure_quote_action_dock_density(window, 400)
assert not window.quote_action_dock_label.isVisible()
compact_actions = [
    window.findChild(QAbstractButton, name)
    for name in ("primaryQuoteAction", "secondaryQuoteAction", "quietQuoteAction")
]
assert all(action.isVisible() for action in compact_actions)
compact_layout = quote_dock.layout()
compact_required = (
    sum(action.minimumWidth() for action in compact_actions)
    + compact_layout.spacing() * 2
    + compact_layout.contentsMargins().left()
    + compact_layout.contentsMargins().right()
)
assert compact_required <= 400, compact_required
layout_refresh._configure_quote_action_dock_density(window, quote_dock.width())

# A normal 1366x768 office window keeps the two-column workbench, while a
# 1180px logical window (for example a 1690px display at 150% scaling) stacks
# the panels. Neither mode may expose horizontal scrolling or hide actions.
window.resize(1366, 768)
app.processEvents()
app.processEvents()
assert quote_workspace.property("responsiveMode") == "medium"
assert quote_workspace.orientation() == Qt.Orientation.Horizontal
medium_left, medium_right = quote_workspace.sizes()
assert medium_left >= 520, quote_workspace.sizes()
assert medium_right >= 500, quote_workspace.sizes()
assert main_scroll.horizontalScrollBar().maximum() == 0
assert quote_dock.isVisible()
assert quote_dock.geometry().top() >= main_scroll.geometry().bottom()
door_block = window.single_door_combo.parentWidget().parentWidget()
quantity_block = window.quantity_spin.parentWidget()
freight_block = window.freight_spin.parentWidget()
assert door_block.geometry().top() == quantity_block.geometry().top() == freight_block.geometry().top()
assert door_block.geometry().right() < quantity_block.geometry().left()
assert quantity_block.geometry().right() < freight_block.geometry().left()
assert window.freight_spin.geometry().top() >= window.freight_label.geometry().bottom()

window.resize(1180, 720)
app.processEvents()
app.processEvents()
assert window.size().width() == 1180
assert quote_workspace.property("responsiveMode") == "stacked"
assert quote_workspace.orientation() == Qt.Orientation.Vertical
assert main_scroll.horizontalScrollBar().maximum() == 0
assert main_scroll.verticalScrollBar().maximum() > 0
stacked_input, stacked_result = quote_workspace.widget(0), quote_workspace.widget(1)
assert stacked_input.geometry().bottom() < stacked_result.geometry().top()
assert quote_dock.isVisible()
assert quote_dock.width() == window.quote_action_dock_host.width()
assert quote_dock.geometry().top() >= main_scroll.geometry().bottom()

window.resize(980, 700)
app.processEvents()
app.processEvents()
assert window.size().width() == 980
assert window.size().height() == 700
assert quote_workspace.property("responsiveMode") == "stacked"
assert quote_workspace.orientation() == Qt.Orientation.Vertical
assert main_scroll.horizontalScrollBar().maximum() == 0
assert main_scroll.verticalScrollBar().maximum() > 0
assert quote_dock.isVisible()
assert quote_dock.width() == window.quote_action_dock_host.width()
for action_name in ("primaryQuoteAction", "secondaryQuoteAction", "quietQuoteAction"):
    action = window.findChild(QAbstractButton, action_name)
    assert action is not None and action.isVisible()
    assert quote_dock.rect().contains(action.geometry())

window.resize(1519, 987)
app.processEvents()
app.processEvents()
assert quote_workspace.property("responsiveMode") == "wide"
assert quote_workspace.orientation() == Qt.Orientation.Horizontal
assert main_scroll.horizontalScrollBar().maximum() == 0

# A product selected by the operator remains sticky while a cabinet is reset,
# added to the summary, or the user visits the summary page and comes back.
# Only another operator activation replaces that retained selection.
window.product_catalog = {
    "JS": {"codes": {"SINGLE": "JS_SINGLE"}, "method": "formula"},
    "JM": {"codes": {"DEFAULT": "JM"}, "method": "quick"},
}
window.product_combo.clear()
window.product_combo.addItem("JS", "JS")
window.product_combo.addItem("JM", "JM")
jm_index = window.product_combo.findData("JM")
window.product_combo.setCurrentIndex(jm_index)
window.product_combo.activated.emit(jm_index)
window.reset_current_cabinet(keep_company=True)
assert window.product_combo.currentData() == "JM"
window.show_section(3)
window.show_section(1)
assert window.product_combo.currentData() == "JM"
js_index = window.product_combo.findData("JS")
window.product_combo.setCurrentIndex(js_index)
window.product_combo.activated.emit(js_index)
window.reset_current_cabinet(keep_company=True)
assert window.product_combo.currentData() == "JS"

history_card = quote_page.findChild(QFrame, "historyPriceCard")
history_table = quote_page.findChild(QTableWidget, "historyPriceTable")
history_state = quote_page.findChild(QLabel, "historyPriceState")
assert history_card is not None
assert history_table is not None and history_table.columnCount() == 2
assert history_table.horizontalHeaderItem(0).text() == "钉钉合同号"
assert history_table.horizontalHeaderItem(1).text() == "价格"
assert history_state is not None and history_state.text() == "等待完整输入"
assert window.width_spin.specialValueText() == ""
assert window.depth_spin.specialValueText() == ""
assert window.height_spin.specialValueText() == ""
window.product_catalog = {"JM": {"codes": {"DEFAULT": "JM"}, "method": "quick"}}
window.product_combo.clear()
window.product_combo.addItem("JM", "JM")
window.product_changed()
for widget, value in (
    (window.company_combo, "浙江万丰科技开发股份有限公司"),
    (window.quote_spec_edit, "1000*600*(1800+200)"),
):
    blocked = widget.blockSignals(True)
    if hasattr(widget, "setEditText"):
        widget.setEditText(value)
    else:
        widget.setText(value)
    widget.blockSignals(blocked)
assert layout_refresh._history_price_match_payload(window) == {
    "company_name": "浙江万丰科技开发股份有限公司",
    "specification": "1000*600*(1800+200)",
    "cabinet_type": "JM",
}
layout_refresh._render_history_price_matches(window, {
    "matched": True,
    "source_row_count": 2,
    "unique_result_count": 1,
    "items": [{
        "dingtalk_contract_no": "ZJN/S-2606098",
        "tax_included_unit_price": 2400,
        "source_row_count": 2,
    }],
})
assert history_table.rowCount() == 1
assert history_table.item(0, 0).text() == "ZJN/S-2606098"
assert history_table.item(0, 1).text() == "2,400.00 元"
assert history_state.text() == "完全匹配 1 条（源表 2 行）"
assert not window.single_door_combo.isEnabled()
assert not window.double_door_combo.isEnabled()
assert window.door_counts() == (1, 0), window.door_counts()
material_index = window.material_combo.findData("SUS304")
coating_index = window.coating_combo.findData("平光")
assert material_index >= 0 and coating_index >= 0
window.material_combo.setCurrentIndex(material_index)
window.coating_combo.setCurrentIndex(coating_index)
window.product_changed()
assert window.material_combo.currentData() == "SUS304"
assert window.coating_combo.currentData() == "平光"
window.material_combo.setCurrentIndex(-1)
window.coating_combo.setCurrentIndex(-1)
window.product_changed()
assert window.material_combo.currentData() == "SECC"
assert window.coating_combo.currentData() == "橘纹"

def final_formula_template_urlopen(request, timeout=0):
    assert request.full_url.endswith("/api/quotes/formula-template")
    assert timeout == layout_refresh.FORMULA_TEMPLATE_REQUEST_TIMEOUT_SECONDS
    product_code = json.loads(request.data.decode("utf-8"))["product_code"]
    return MockHttpResponse({
        "template": {
            "template_code": product_code,
            "option_cells": {"defaults": {}},
            "rules": [],
        }
    })


layout_refresh.urllib.request.urlopen = final_formula_template_urlopen
window.product_catalog = {"JA": {"codes": {"SINGLE": "JA_SINGLE"}, "method": "formula"}}
window.product_combo.clear()
window.product_combo.addItem("JA", "JA")
window.single_door_combo.setEnabled(True)
window.double_door_combo.setEnabled(True)
window.set_door_counts(0, 0)
layout_refresh._set_default_door_combination(window)
assert window.door_counts() == (1, 0), window.door_counts()

window.attachments = [
    {"item_name": "门限位器", "category_level1": "门限位器", "quantity": 1},
    {"item_name": "A4资料盒", "category_level1": "文件夹", "quantity": 9},
]
window.attachment_default_opt_outs = set()
window.attachment_default_quantity_overrides = set()
window._attachment_default_door_counts = (1, 0)
window.set_door_counts(0, 2)
window.door_counts_changed("double")
assert window.attachments[0]["quantity"] == 4
assert window.attachments[1]["quantity"] == 9

window.attachments[0]["quantity"] = 7
window.attachment_default_quantity_overrides = {"door_limiter"}
window._attachment_default_door_counts = (0, 2)
window.set_door_counts(1, 1)
window.door_counts_changed("single")
assert window.attachments[0]["quantity"] == 7

window.attachments = [window.attachments[1]]
window.attachment_default_quantity_overrides = set()
window.attachment_default_opt_outs = {"door_limiter"}
window._attachment_default_door_counts = (1, 1)
window.set_door_counts(2, 0)
window.door_counts_changed("single")
assert not any(item.get("item_name") == "门限位器" for item in window.attachments)
assert "宽×深×高" in window.quote_spec_edit.toolTip()

window.stack.setCurrentIndex(3)
app.processEvents()
app.processEvents()
summary_page = window.stack.widget(3)
assert not quote_dock.isVisible()
assert main_scroll.viewportMargins().bottom() == 0
empty_action = summary_page.findChild(QPushButton, "emptyStateAction")
assert empty_action is not None and empty_action.isVisible()
list_actions = buttons_with_text(summary_page, {"编辑", "删除", "上移", "下移"})
assert len(list_actions) == 4
assert all(not action.isEnabled() for action in list_actions)

summary_table = window.summary_table
summary_table.setRowCount(1)
summary_table.setItem(0, 0, QTableWidgetItem("1"))
summary_table.selectRow(0)
layout_refresh._sync_summary_action_state(window)
app.processEvents()
assert all(action.isEnabled() for action in list_actions)
assert not empty_action.isVisible()

if artifact_dir is not None:
    candidate_table.setRowCount(0)
    layout_refresh._sync_recognition_action_state(window)
    summary_table.setRowCount(0)
    layout_refresh._sync_summary_action_state(window)
    for index, name in ((0, "recognition"), (1, "quote"), (3, "summary")):
        window.show_section(index)
        app.processEvents()
        assert window.grab().save(str(artifact_dir / f"v3_{name}_refresh.png"))
    window.show_section(1)
    window.resize(1366, 768)
    app.processEvents()
    app.processEvents()
    assert window.grab().save(str(artifact_dir / "v3_quote_medium_1366x768.png"))
    window.resize(980, 700)
    app.processEvents()
    app.processEvents()
    assert window.grab().save(str(artifact_dir / "v3_quote_stacked_980x700.png"))

    # Qt lays out widgets in logical pixels.  Resize to the logical desktop
    # sizes produced by the requested physical resolutions/scales, then keep
    # an evidence image for each combination.  The production minimum-size
    # pass uses the real screen geometry; the test temporarily lowers the
    # offscreen plugin's synthetic 800x800 minimum so smaller logical desktops
    # can be exercised accurately.
    previous_minimum = window.minimumSize()
    window.setMinimumSize(1, 1)
    scaling_cases = {
        "1920x1080_scale125": (1536, 864),
        "1920x1080_scale150": (1280, 720),
        "1920x1080_scale175": (1097, 617),
        "1920x1080_scale200": (960, 540),
        "1366x768_scale125": (1093, 614),
        "1366x768_scale150": (911, 512),
        "1366x768_scale175": (781, 439),
        "1366x768_scale200": (683, 384),
    }
    for case_name, logical_size in scaling_cases.items():
        window.resize(*logical_size)
        app.processEvents()
        app.processEvents()
        assert window.size().toTuple() == logical_size, (case_name, window.size())
        assert main_scroll.horizontalScrollBar().maximum() == 0, case_name
        assert quote_dock.isVisible(), case_name
        for action_name in (
            "primaryQuoteAction",
            "secondaryQuoteAction",
            "quietQuoteAction",
        ):
            action = window.findChild(QAbstractButton, action_name)
            assert action is not None and action.isVisible(), (case_name, action_name)
            assert quote_dock.rect().contains(action.geometry()), (case_name, action_name)
        assert window.grab().save(
            str(artifact_dir / f"v3_quote_{case_name}.png")
        )
    window.setMinimumSize(previous_minimum)

deadline = time.monotonic() + 5
while (
    any(
        worker.isRunning()
        for worker in window.findChildren(layout_refresh._FormulaTemplateWorker)
    )
    and time.monotonic() < deadline
):
    app.processEvents()
    time.sleep(0.01)
layout_refresh.urllib.request.urlopen = original_urlopen

window.close()
app.processEvents()

print("V3_LAYOUT_REFRESH=PASS")
print(f"WORKBENCH_SIZES={workbench.sizes()}")
print(f"QUOTE_SIZES={quote_workspace.sizes()}")
