"""Focused offline contract and screenshot check for the approved scheme-2 UI."""

from __future__ import annotations

import os
from pathlib import Path
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import v3_launcher  # noqa: E402
import scheme2_ui  # noqa: E402


namespace = v3_launcher.load_v3_namespace()
app = QApplication.instance() or QApplication([])
windows_yahei = Path(r"C:\Windows\Fonts\msyh.ttc")
if windows_yahei.is_file():
    QFontDatabase.addApplicationFont(str(windows_yahei))
namespace["AttachmentDialog"].load_catalog = lambda self, _url: None
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()

assert window.minimumWidth() == 1024 and window.minimumHeight() == 700
assert window.nav_routes == ((1, "选项配置", "", None), (3, "成本计算", "", None))
assert [button.text() for button in window.nav_buttons] == ["选项配置", "成本计算"]
assert window.stack.widget(1).objectName() == "scheme2OptionPage"
assert window.stack.widget(3).objectName() == "scheme2CostPage"
assert window.stack.widget(5).objectName() == "scheme2DetailPage"
assert [window.summary_table.horizontalHeaderItem(i).text() for i in range(16)] == [
    "序号", "名称", "产品", "尺寸", "材料成本", "辅材成本", "人工成本", "附件成本",
    "喷涂费用", "管理费用", "运费", "数量", "成本单价", "面价", "已选附件", "成本明细",
]
assert window.summary_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
assert window.summary_table.rowCount() == 0
assert not window.scheme2_cost_export.isEnabled()
assert not window.scheme2_cost_empty.isHidden()
assert len(window.scheme2_shortcuts) >= 8
assert window.quote_date.isHidden() or window.quote_date.parentWidget().isHidden()
assert window.quote_date.date().toString("yyyy-MM-dd") == __import__("datetime").date.today().isoformat()
assert window.scheme2_add_button.text() == "加入报价清单"
form_layout = window.scheme2_name_edit.parentWidget().parentWidget().layout()
assert form_layout.indexOf(window.scheme2_name_edit.parentWidget()) < form_layout.indexOf(window.product_combo.parentWidget())
assert not window.model_edit.isVisible()
assert window.quote_spec_edit.isVisible()
assert not window.width_spin.isVisible() and not window.depth_spin.isVisible() and not window.height_spin.isVisible()
assert window.scheme2_completion.parentWidget().objectName() == "scheme2DrawingHeader"
preview_buttons = {button.text(): button for button in window.quote_drawing_preview.findChildren(QPushButton)}
assert not preview_buttons["左转"].isHidden() and not preview_buttons["右转"].isHidden()
assert all(preview_buttons[text].isHidden() for text in ("手写笔", "框选", "撤销", "删除选中", "清除"))

attachment_button = window.findChild(QPushButton, "quietAction")
left_scroll = window.findChild(__import__("PySide6.QtWidgets").QtWidgets.QScrollArea, "scheme2OptionScroll")
scheme2_ui._open_attachment_overlay(window, namespace["AttachmentDialog"], left_scroll)
app.processEvents()
overlay = window._scheme2_attachment_overlay
assert overlay.isVisible() and overlay.width() == left_scroll.width()
assert any("新增附件" in button.text() and button.isVisible() for button in overlay.findChildren(QPushButton))
custom_toggle = next(button for button in overlay.findChildren(QPushButton)
                     if "新增附件" in button.text() and button.isVisible())
custom_toggle.click()
custom_name = next(
    edit for edit in overlay.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QLineEdit)
    if edit.placeholderText() == "请输入附件名称"
)
custom_name.setText("测试自定义附件")
custom_add = next(button for button in overlay.findChildren(QPushButton) if button.text() == "添加" and button.isVisible())
custom_add.click()
assert "已新增 1 项" in custom_toggle.text()
assert window.quote_drawing_preview.isVisible()
assert all(button.isHidden() for button in overlay.findChildren(QPushButton) if "附件库" in button.text() or "重新读取价格" in button.text())
if hasattr(overlay, "table"):
    for column in range(overlay.table.columnCount()):
        header = overlay.table.horizontalHeaderItem(column)
        if header is not None and any(word in header.text() for word in ("价格", "单价", "金额")):
            assert overlay.table.isColumnHidden(column)
overlay.reject()
app.processEvents()

calculate_calls = []
window.current_result = None
window.calculate = lambda: calculate_calls.append(True)
window.scheme2_add_button.click()
assert calculate_calls == [True] and window._scheme2_add_after_calculate is True
assert window.scheme2_add_progress.isVisible() and window.scheme2_add_progress.value() >= 1
window._scheme2_add_after_calculate = False
window.scheme2_add_button.setEnabled(True)
window.scheme2_add_button.setText("加入报价清单")
QTest.qWait(200)
window.scheme2_add_progress.hide()

sample = {
    "name": "进线柜-01", "model_code": "旧内部型号", "product_code": "JP",
    "specification": "(400+400)*600*1800", "quantity": 2, "freight_fee": 50,
    "quick_discount": .85,
    "formula": {"material_cost": 200, "auxiliary_cost": 30, "labor_cost": 80,
                "attachment_fee": 20, "spray_cost": 40, "management_fee": 10,
                "total_cost": 380},
    "quick": {"attachment_fee": 20, "total_cost": 520},
    "attachments": [{"item_name": "风机", "quantity": 1, "matched_price": 20}],
}
window.draft_items = [sample]
window.refresh_summary()
assert window.summary_table.rowCount() == 2
assert window.summary_table.item(0, 1).text() == "进线柜-01"
assert window.summary_table.item(0, 10).flags() & Qt.ItemFlag.ItemIsEditable
assert window.summary_table.item(0, 11).flags() & Qt.ItemFlag.ItemIsEditable
assert not window.summary_table.item(0, 12).flags() & Qt.ItemFlag.ItemIsEditable
assert window.summary_table.item(0, 13).text() == "484.50"
assert window.summary_table.item(1, 11).text() == "2"
assert window.summary_table.item(1, 12).text() == "860.00"
assert window.summary_table.item(1, 13).text() == "969.00"
assert all(not window.summary_table.isColumnHidden(column) for column in (0, 1, 2, 3, 11, 12, 13, 15))
assert window.summary_table.isColumnHidden(4)
scheme2_ui._set_cost_column_mode(window, True)
assert not any(window.summary_table.isColumnHidden(column) for column in range(16))
scheme2_ui._set_cost_column_mode(window, False)
window.summary_table.selectRow(0)
scheme2_ui._duplicate_selected(window)
assert len(window.draft_items) == 2 and window.draft_items[1]["name"].endswith("副本")
scheme2_ui._delete_selected(window)
assert len(window.draft_items) == 1 and not window.scheme2_cost_undo.isHidden()
scheme2_ui._undo_delete(window)
assert len(window.draft_items) == 2
window.draft_items = [sample]
window.refresh_summary()

window.summary_table.selectRow(0)
window.summary_table.item(0, 10).setText("75")
app.processEvents()
assert sample["freight_fee"] == 75
window.summary_table.item(0, 11).setText("3")
app.processEvents()
assert sample["quantity"] == 3

scheme2_ui._show_detail(window, sample)
factor = window.scheme2_detail_table.cellWidget(0, 8)
assert factor.minimum() == .01 and factor.maximum() == 10 and factor.decimals() == 4
factor.setValue(2)
detail_back = next(button for button in window.scheme2_detail_page.findChildren(QPushButton) if "返回成本计算" in button.text())
detail_back.click()
app.processEvents()
assert sample["formula"]["material_cost"] == 400
assert sample["formula"]["total_cost"] == 580

output = ROOT / "outputs" / "scheme2-ui-qa"
output.mkdir(parents=True, exist_ok=True)

window.resize(1366, 820)
window.show_section(1)
app.processEvents()
scheme2_ui._open_attachment_overlay(window, namespace["AttachmentDialog"], left_scroll)
app.processEvents()
window._scheme2_attachment_overlay.grab().save(str(output / "attachment-overlay-1366x820.png"))
window._scheme2_attachment_overlay.reject()
app.processEvents()

scheme2_ui._show_detail(window, sample)
app.processEvents()
assert window.scheme2_detail_page.height() >= 760, (
    window.scheme2_detail_page.size(), window.scheme2_detail_table.size(),
    window.stack.size(), window.stack.parentWidget().size(),
)
assert window.scheme2_detail_table.height() >= 680
assert window.scheme2_detail_page.height() - window.scheme2_detail_table.geometry().bottom() <= 24
window.grab().save(str(output / "cost-detail-1366x820.png"))
detail_back.click()
app.processEvents()

discount_dialog = scheme2_ui.FaceDiscountEditor(window, sample)
discount_dialog.show()
app.processEvents()
discount_dialog.grab().save(str(output / "face-discount-dialog.png"))
discount_dialog.close()

attachment_editor = scheme2_ui.AttachmentEditor(window, sample)
attachment_editor.show()
app.processEvents()
attachment_editor.grab().save(str(output / "attachment-editor-dialog.png"))
attachment_editor.close()

for width, height in ((1680, 980), (1366, 820), (1100, 720), (1024, 700)):
    window.resize(width, height)
    window.show_section(1)
    app.processEvents()
    window.grab().save(str(output / f"options-{width}x{height}.png"))
    splitter = window.scheme2_option_splitter
    assert splitter.orientation() == Qt.Orientation.Horizontal
    assert splitter.widget(0) is window.scheme2_option_form_widget
    assert abs(window.quote_drawing_preview.canvas.width() / window.quote_drawing_preview.canvas.height() - 297 / 210) < .02
    window.show_section(3)
    app.processEvents()
    window.grab().save(str(output / f"cost-{width}x{height}.png"))
    assert window.scheme2_nav.isHidden()
    assert window.scheme2_compact_coefficients.isVisible() == (width < 1100)

window.close()
print(f"scheme2 UI contract passed; screenshots: {output}")
