"""Runtime contract check for the source-controlled V3 layout overlay.

The verified client core remains an external build artifact.  Point
``AI_QUOTE_V3_CORE_ROOT`` at its ``_internal/v3_core`` directory and run this
script with the Python 3.12/PySide6 environment used to build the client.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "desktop_client"
sys.path.insert(0, str(CLIENT_ROOT))

core_root = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core_root.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core directory")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QAbstractButton,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

import layout_refresh  # noqa: E402
import v3_launcher  # noqa: E402


def buttons_with_text(root, captions: set[str]):
    return [
        button
        for button in root.findChildren(QAbstractButton)
        if button.text().replace("&", "").strip() in captions
    ]


namespace = v3_launcher.load_v3_namespace()

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
assert runtime_calculator.DETAIL_ROWS["JP_SINGLE"][:3] == (5, 26, 29)
assert runtime_calculator.DOOR_CONTROL_CELLS["JE_SINGLE"] == ("B16", "B17")
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
attachment_dialog.resize(1050, 680)
attachment_dialog.show()
app.processEvents()

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
    "门限位器", "门加强筋", "接地线", "未来分类",
]
positions = [
    attachment_dialog.category_grid.getItemPosition(
        attachment_dialog.category_grid.indexOf(button.parentWidget())
    )[:2]
    for button in level1_buttons
]
assert positions[:5] == [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0)], positions
assert attachment_dialog.table.isHidden()
quick_match_buttons = attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchSelected")
assert len(quick_match_buttons) == 7
assert any(button.text() == "默认已选择\n类型：固定 · 高度：100 mm" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\nA4资料盒" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n门加强筋" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n红绿线" for button in quick_match_buttons)
assert any(button.text() == "默认已选择\n门限位器 · 数量：1 个" for button in quick_match_buttons)

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
]) == 6
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
]) == 7
if artifact_dir is not None:
    assert attachment_dialog.grab().save(str(artifact_dir / "v3_attachment_categories.png"))

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
folder_manual = next(
    button for button in attachment_dialog.findChildren(QPushButton, "attachmentQuickMatchManual")
    if button.isVisible() and "A3资料盒" in button.text()
)
folder_manual.click()
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
assert plain_dialog.prepare_default_selections() == 5
plain_dialog.rebuild_table()
plain_dialog.show()
app.processEvents()
plain_quick_labels = plain_dialog.findChildren(QPushButton, "attachmentQuickMatch")
assert any(label.text() == "快速匹配\n无需底座" for label in plain_quick_labels)
assert any(label.text() == "快速匹配\n仅 JP 默认匹配" for label in plain_quick_labels)
assert sum(
    plain_dialog.table.item(row, plain_dialog.COL_CHECK).checkState() == Qt.CheckState.Checked
    for row in range(plain_dialog.table.rowCount())
) == 5
plain_dialog.close()
plain_parent.close()
attachment_dialog_class.load_catalog = original_attachment_load

window = namespace["MainWindow"]()
window.resize(1519, 987)
window.show()
app.processEvents()

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
    "width_mm": 1000,
    "height_mm": 1800,
    "depth_mm": 600,
    "material_code": "SECC",
    "quantity": 2,
    "attachments": [dict(item) for item in window.attachments],
    "formula": dict(window._formula_base_result),
    "formula_discount": 1,
    "quick": {"attachment_fee": 392, "total_cost": 4406.29},
    "quick_discount": 0.95,
    "notes": "选择性折扣测试",
}]
window.refresh_summary()
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
assert window.summary_table.item(0, quick_price_columns[0]).text() == "4,190.58"
assert "8,381.15" in window.summary_quick_total.text(), window.summary_quick_total.text()
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
assert quote_left >= 570, quote_workspace.sizes()
assert 520 <= quote_right <= 680, quote_workspace.sizes()
assert window.findChild(QAbstractButton, "primaryQuoteAction").accessibleName() == "计算双报价"

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
summary_page = window.stack.widget(3)
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

window.close()
app.processEvents()

print("V3_LAYOUT_REFRESH=PASS")
print(f"WORKBENCH_SIZES={workbench.sizes()}")
print(f"QUOTE_SIZES={quote_workspace.sizes()}")
