"""Focused offline contract and screenshot check for the approved scheme-2 UI."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
core = Path(os.environ.get("AI_QUOTE_V3_CORE_ROOT", ""))
if not core.is_dir():
    raise RuntimeError("AI_QUOTE_V3_CORE_ROOT must point to the verified V3 core")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialogButtonBox, QFrame, QLabel, QPushButton, QToolButton  # noqa: E402
from pypdf import PdfWriter  # noqa: E402

import v3_launcher  # noqa: E402
import scheme2_ui  # noqa: E402
import attachment_v2_client  # noqa: E402


duplicate_name_catalog = [
    {"attachment_price_id": 11, "category_level1": "控制箱附件", "item_name": "内门"},
    {"attachment_price_id": 12, "category_level1": "控制柜附件", "item_name": "内门"},
]
assert attachment_v2_client.match_catalog_attachment(
    {"category_level1": "控制柜附件", "item_name": "内门"}, duplicate_name_catalog
)["attachment_price_id"] == 12


namespace = v3_launcher.load_v3_namespace()
app = QApplication.instance() or QApplication([])
windows_yahei = Path(r"C:\Windows\Fonts\msyh.ttc")
if windows_yahei.is_file():
    QFontDatabase.addApplicationFont(str(windows_yahei))
attachment_catalog_loads = []
namespace["AttachmentDialog"].load_catalog = lambda self, url: attachment_catalog_loads.append(url)
namespace["MainWindow"].load_catalogs = lambda self: None
window = namespace["MainWindow"]()
window.show()
app.processEvents()


def wait_until(predicate, attempts=300):
    for _ in range(attempts):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("timed out waiting for UI state")

assert window.minimumWidth() == 1024 and window.minimumHeight() == 700
assert window.nav_routes == ((1, "选项配置", "", None), (3, "成本计算", "", None))
assert [button.text() for button in window.nav_buttons] == ["选项配置", "成本计算"]
assert window.scheme2_nav.width() == scheme2_ui.NAV_EXPANDED_WIDTH
assert all(button.height() == 28 for button in window.nav_buttons)
assert window.scheme2_nav.findChild(__import__("PySide6.QtWidgets").QtWidgets.QLabel, "scheme2NavLogo").size().width() == 26
assert window.scheme2_nav.findChild(QPushButton, "scheme2CollapseButton").size().width() == 28
assert window.stack.widget(1).objectName() == "scheme2OptionPage"
assert window.stack.widget(1).findChild(QFrame, "scheme2TopBar") is None
assert not hasattr(window, "scheme2_saved_status")
service_status = window.scheme2_nav.findChild(QLabel, "scheme2ServiceStatus")
assert service_status is window.scheme2_service_status
assert "报价" in service_status.text() and service_status.y() > window.nav_buttons[-1].y()
assert window.stack.widget(3).objectName() == "scheme2CostPage"
assert window.stack.widget(5).objectName() == "scheme2DetailPage"
assert [window.summary_table.horizontalHeaderItem(i).text() for i in range(16)] == [
    "序号", "名称", "产品", "尺寸", "材料成本", "辅材成本", "人工成本", "附件成本",
    "喷涂费用", "管理费用", "运费", "数量", "成本单价", "面价", "已选附件", "成本明细",
]
assert window.summary_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
assert window.summary_table.rowCount() == 0
assert not window.scheme2_cost_export.isEnabled()
assert window.scheme2_cost_export.text() == "导出报价单"
assert not any(button.text() == "编辑选中项" for button in window.scheme2_cost_page.findChildren(QPushButton))
cost_return = window.scheme2_cost_return
cost_delete = next(button for button in window.scheme2_cost_action_buttons if button.text() == "× 删除")
assert cost_return.text() == "返回" and cost_return.size() == cost_delete.size()
window.show_section(3)
cost_return.click()
app.processEvents()
assert window.stack.currentIndex() == scheme2_ui.OPTION_ROUTE
assert not window.scheme2_cost_empty.isHidden()
assert not any(button.text() == "返回选项配置" for button in window.scheme2_cost_page.findChildren(QPushButton))
assert window.scheme2_company.minimumWidth() == 0
assert window.scheme2_company.maximumWidth() == 16777215
assert window.scheme2_cost_sidebar.width() == scheme2_ui.COST_SIDEBAR_WIDTH == 130
assert window.scheme2_company.height() == scheme2_ui.COMPANY_COMBO_HEIGHT == 56, (
    window.scheme2_company.height(), window.scheme2_company.minimumHeight(), window.scheme2_company.maximumHeight()
)
assert window.scheme2_company.view().wordWrap()
assert window.scheme2_company.view().textElideMode() == Qt.TextElideMode.ElideNone
assert window.scheme2_company.isEditable()
assert not window.scheme2_company.lineEdit().isReadOnly()
assert window.scheme2_company.lineEdit().focusPolicy() == Qt.FocusPolicy.StrongFocus
assert not window.scheme2_company.lineEdit().testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
assert hasattr(window.scheme2_company, "_scheme2_multiline_filter")
assert window.scheme2_cost_sidebar.findChild(
    __import__("PySide6.QtWidgets").QtWidgets.QLabel, "scheme2SidebarHint"
) is None
assert len(window.scheme2_shortcuts) >= 8
assert window.quote_date.isHidden() or window.quote_date.parentWidget().isHidden()
assert window.quote_date.date().toString("yyyy-MM-dd") == __import__("datetime").date.today().isoformat()
assert window.scheme2_add_button.text() == "加入报价清单"
assert window.scheme2_attachment_summary.findChild(QLabel, "scheme2AttachmentEmpty").text() == "未选择附件"
assert window.attachment_summary_table.isHidden()
assert not window.scheme2_name_edit.isVisible()
assert window.product_combo.minimumHeight() >= 50
assert window.quote_spec_edit.minimumHeight() >= 50
assert all(
    window.coating_combo.itemText(index).strip() != "皱纹"
    and str(window.coating_combo.itemData(index) or "").strip() != "皱纹"
    for index in range(window.coating_combo.count())
)
for combo in (window.product_combo, window.material_combo, window.coating_combo, window.scheme2_color_combo):
    assert combo.view().objectName() == "scheme2OptionDropdown"
    assert combo.parentWidget().findChild(QToolButton, "scheme2DropdownIndicator") is None
for combo in (window.material_combo, window.coating_combo, window.scheme2_color_combo):
    assert not combo.isHidden()
    assert combo.isVisibleTo(window)
assert [window.material_combo.itemText(index) for index in range(window.material_combo.count())] == [
    "碳钢 SECC", "不锈钢 SUS304", "不锈钢 SUS316",
]
assert [window.coating_combo.itemText(index) for index in range(window.coating_combo.count())] == ["无", "平光", "橘纹"]
assert [window.scheme2_color_combo.itemText(index) for index in range(window.scheme2_color_combo.count())] == [
    "RAL7035 浅灰", "RAL7032 灰", "RAL9005 黑", "RAL9016 白", "RAL5015 蓝", "自定义…",
]
for combo in (window.material_combo, window.coating_combo, window.scheme2_color_combo):
    assert combo.view().itemDelegate().objectName() == "scheme2DropdownItemDelegate"
    assert combo.maxVisibleItems() == combo.count()
    assert combo.view().verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
for combo in (window.material_combo, window.coating_combo):
    assert combo.count() > 1
    current = combo.currentIndex()
    if current < 0:
        combo.setCurrentIndex(0)
        current = 0
    target = current + 1 if current < combo.count() - 1 else current - 1
    combo.setCurrentIndex(target)
    combo.activated.emit(target)
    app.processEvents()
    assert combo.currentIndex() == target, (combo.objectName(), current, target, combo.currentIndex(), [combo.itemText(i) for i in range(combo.count())])
window.scheme2_color_combo.lineEdit().selectAll()
QTest.keyClicks(window.scheme2_color_combo.lineEdit(), "RAL7016")
assert bool(window.scheme2_color_combo.property("manualEntry"))
assert window.scheme2_color_combo.currentText() == "RAL7016"
color_custom = window.scheme2_color_combo.findText("自定义…")
window.scheme2_color_combo.setCurrentIndex(color_custom)
window.scheme2_color_combo.activated.emit(color_custom)
assert window.scheme2_color_combo.isEditable()
assert window.scheme2_color_combo.property("manualEntry") is True
assert window.scheme2_color_combo.lineEdit().objectName() == "scheme2ColorManualInput"
assert window.scheme2_color_combo.lineEdit().placeholderText() == "请输入自定义颜色"
assert window.scheme2_color_combo.lineEdit().isClearButtonEnabled()
window.scheme2_color_combo.lineEdit().setText("RAL3020 红")
assert window.scheme2_color_combo.currentText() == "RAL3020 红"
assert window.findChild(__import__("PySide6.QtWidgets").QtWidgets.QScrollArea, "scheme2OptionScroll").verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
assert not window.model_edit.isVisible()
assert window.quote_spec_edit.isVisible()
assert not window.width_spin.isVisible() and not window.depth_spin.isVisible() and not window.height_spin.isVisible()
assert window.scheme2_completion.parentWidget().objectName() == "scheme2DrawingHeader"
import_button = next(button for button in window.scheme2_drawing_widget.findChildren(QPushButton) if button.text() == "导入图纸")
assert import_button.isVisibleTo(window)
assert not any(button.text() == "导入 / 管理图纸" for button in window.findChildren(QPushButton))
window.show_section(0)
assert window.stack.currentIndex() == scheme2_ui.OPTION_ROUTE
preview_buttons = {button.text(): button for button in window.quote_drawing_preview.findChildren(QPushButton)}
assert not preview_buttons["左转"].isHidden() and not preview_buttons["右转"].isHidden()
assert all(preview_buttons[text].isHidden() for text in ("手写笔", "框选", "撤销", "删除选中", "清除"))

window.quote_spec_edit.setText("800*600*2000")
window.material_combo.setCurrentIndex(window.material_combo.findData("SUS304"))
window.coating_combo.setCurrentIndex(window.coating_combo.findText("平光"))
window.scheme2_color_combo.setEditText("RAL7016 深灰")
window.attachments = [{"item_name": "内门", "quantity": 1}]
saved_page = scheme2_ui._capture_scheme2_page_state(window)
window.quote_spec_edit.setText("600*400*1200")
window.material_combo.setCurrentIndex(window.material_combo.findData("SECC"))
window.attachments = []
scheme2_ui._restore_scheme2_page_state(window, saved_page)
assert window.quote_spec_edit.text() == "800*600*2000"
assert window.material_combo.currentData() == "SUS304"
assert window.coating_combo.currentText() == "平光"
assert window.scheme2_color_combo.currentText() == "RAL7016 深灰"
assert window.attachments == [{"item_name": "内门", "quantity": 1}]

recognition_calls = []


class FakePageRecognition:
    @classmethod
    def recognize_document(cls, path):
        recognition_calls.append(path)
        number = len(recognition_calls)
        return {"cabinet_candidates": [{
            "candidate_id": f"page-{number}", "confirmed": True, "verified": True,
            "product_code": "JP", "specification": f"{700 + number * 10}*600*2000",
            "material_code": "SECC", "coating": "橘纹", "color": "RAL7035 浅灰",
        }]}


with tempfile.TemporaryDirectory(prefix="scheme2-pages-") as folder:
    source = Path(folder) / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as stream:
        writer.write(stream)
    window._scheme2_recognition_tools = FakePageRecognition
    scheme2_ui._import_scheme2_drawings(window, [str(source)])
    wait_until(lambda: window._scheme2_page_worker is None)
    assert len(window._scheme2_drawing_pages) == 2
    assert len(recognition_calls) == 1
    assert window._scheme2_drawing_page_index == 0
    window.quote_spec_edit.setText("第一页人工保留")
    window.material_combo.setCurrentIndex(window.material_combo.findData("SUS304"))
    scheme2_ui._change_scheme2_page(window, 1)
    wait_until(lambda: window._scheme2_page_worker is None)
    assert len(recognition_calls) == 2
    assert window._scheme2_drawing_page_index == 1
    scheme2_ui._change_scheme2_page(window, -1)
    app.processEvents()
    assert len(recognition_calls) == 2
    assert window.quote_spec_edit.text() == "第一页人工保留"
    assert window.material_combo.currentData() == "SUS304"
    # High-DPI preview rendering is asynchronous; let pdftoppm release the
    # temporary source before TemporaryDirectory removes it on Windows.
    wait_until(lambda: not window.quote_drawing_preview._workers)

window.quote_spec_edit.setText("(400+400+400)*600*400")
window.quote_spec_edit.textEdited.emit(window.quote_spec_edit.text())
app.processEvents()
QTest.qWait(20)
assert window.scheme2_ganged_dimensions.isVisible()
assert window.scheme2_ganged_doors.isVisible()
assert not window.scheme2_regular_doors.isVisible()
ganged_labels = [label.text() for label in window.scheme2_ganged_dimensions.findChildren(
    __import__("PySide6.QtWidgets").QtWidgets.QLabel, "scheme2GangedLabel"
)]
assert ganged_labels == ["柜体 1", "柜体 2", "柜体 3"], ganged_labels
window.quote_spec_edit.clear()
window.quote_spec_edit.textEdited.emit("")
app.processEvents()
QTest.qWait(20)
scheme2_ui._set_dirty(window, False)

attachment_button = window.findChild(QPushButton, "quietAction")
left_scroll = window.findChild(__import__("PySide6.QtWidgets").QtWidgets.QScrollArea, "scheme2OptionScroll")
window.product_combo.clear()
window.product_combo.addItem("JP", "JP")
scheme2_ui._open_attachment_overlay(window, namespace["AttachmentDialog"], left_scroll)
app.processEvents()
overlay = window._scheme2_attachment_overlay
assert overlay.isVisible() and overlay.width() == left_scroll.width()
assert overlay.windowTitle() == "附件选择"
assert attachment_catalog_loads == []
assert not hasattr(overlay, "catalog_hint") and not hasattr(overlay, "table") and not hasattr(overlay, "_v2_timer")
assert overlay.category_names == [
    category for category in scheme2_ui.ATTACHMENT_CATEGORY_ORDER if category != "控制箱附件"
]
close_attachment = overlay.findChild(QToolButton, "scheme2AttachmentClose")
assert close_attachment is not None and close_attachment.isVisible() and close_attachment.text() == "×"
attachment_check = overlay.category_checks["安装附件"]
attachment_combo = overlay.category_combos["安装附件"]
assert not attachment_combo.isEnabled() and attachment_combo.itemText(0) == "未选择"
attachment_check.setChecked(True)
assert attachment_combo.isEnabled()
fixed_column = attachment_combo.findText("固定立柱")
attachment_combo.setCurrentIndex(fixed_column)
attachment_combo.activated.emit(fixed_column)
assert attachment_combo.currentText() == "固定立柱"
assert attachment_combo.view().objectName() == "scheme2AttachmentDropdown"
assert attachment_combo.view().itemDelegate().objectName() == "scheme2DropdownItemDelegate"
fan_combo = overlay.category_combos["风机"]
assert fan_combo.maxVisibleItems() == 6
assert fan_combo.view().verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
actions = overlay.findChild(QDialogButtonBox, "scheme2AttachmentActions")
assert actions.button(QDialogButtonBox.StandardButton.Ok).text() == "确认选择"
assert actions.button(QDialogButtonBox.StandardButton.Cancel).text() == "取消"
actions.button(QDialogButtonBox.StandardButton.Ok).click()
app.processEvents()
assert window.attachments == [{
    "item_name": "固定立柱", "name": "固定立柱", "category_level1": "安装附件",
    "category_level2": "固定立柱", "attachment_category": "安装附件", "quantity": 1,
}]
assert not any(key in window.attachments[0] for key in ("price", "matched_price", "unit_price_override", "attachment_price_id"))
jk_overlay = scheme2_ui._SchemeAttachmentDialog([], "JK", window)
assert "侧板" not in jk_overlay.category_names and "控制柜附件" not in jk_overlay.category_names
assert "JK安装板" in [
    jk_overlay.category_combos["控制箱附件"].itemText(index)
    for index in range(jk_overlay.category_combos["控制箱附件"].count())
]
jk_overlay.close()
duplicate_overlay = scheme2_ui._SchemeAttachmentDialog([
    {"category_level1": "控制箱附件", "item_name": "内门"},
], "JA", window)
assert duplicate_overlay.category_combos["控制箱附件"].currentText() == "内门"
assert "控制柜附件" not in duplicate_overlay.category_names
duplicate_overlay.close()

deferred_events = []
window.current_result = None
window.calculate = lambda: deferred_events.append("calculate")

def resolve_for_quote(succeeded, _failed):
    deferred_events.append("catalog")
    assert window.attachments[0].get("attachment_price_id") is None
    window.attachments[0].update(attachment_price_id=101, catalog_version="test-v2")
    succeeded()

window.resolve_attachments_for_quote = resolve_for_quote
window.scheme2_add_button.click()
assert deferred_events == ["catalog", "calculate"] and window._scheme2_add_after_calculate is True
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
                "cabinet_auxiliary_lines": [
                    {"item_name": "AE箱铰链", "spec_model": "焊接部分配件不要", "internal_quantity": 3,
                     "unit": "件", "unit_price": 2, "line_total": 6},
                    {"item_name": "MS821", "spec_model": "RAL7035", "material_name": "塑料",
                     "internal_quantity": 3, "unit": "件", "unit_price": 8, "line_total": 24},
                ],
                "labor_method": "LINEAR_WEIGHT",
                "labor_source_formula": "人工 = 66.2737 + 4.507871 × 计价材料重量",
                "management_fee_rate": .125,
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
assert all(not window.summary_table.isColumnHidden(column) for column in (0, 1, 2, 3, 10, 11, 12, 13, 14, 15))
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
detail_names = [window.scheme2_detail_table.item(row, 1).text() for row in range(window.scheme2_detail_table.rowCount())]
assert detail_names[:4] == ["材料成本", "AE箱铰链", "MS821", "柜体人工成本"]
assert "3 件 × 2.0000 元/件 = 6.00 元" in window.scheme2_detail_table.item(1, 3).text()
management_row = next(row for row in range(window.scheme2_detail_table.rowCount()) if window.scheme2_detail_table.item(row, 0).text() == "管理费用")
assert window.scheme2_detail_table.item(management_row, 2).text() == "人工成本的 12.5%"
assert window.scheme2_detail_table.item(window.scheme2_detail_table.rowCount() - 1, 1).text() == "合计成本"
assert window.scheme2_detail_table.verticalHeader().isHidden()
factor = window.scheme2_detail_table.cellWidget(0, 8)
assert factor.minimum() == 0 and factor.maximum() == 10 and factor.decimals() == 4
factor.setValue(2)
detail_back = next(button for button in window.scheme2_detail_page.findChildren(QPushButton) if "返回成本计算" in button.text())
detail_back.click()
app.processEvents()
assert sample["formula"]["material_cost"] == 400, (sample["formula"], sample.get("cost_detail_rows"))
assert sample["formula"]["total_cost"] == 580

output = ROOT / "outputs" / "scheme2-ui-qa"
output.mkdir(parents=True, exist_ok=True)

window.resize(1366, 820)
window.show_section(1)
app.processEvents()
window.material_combo.showPopup()
app.processEvents()
window.material_combo.view().window().grab().save(str(output / "material-dropdown.png"))
window.material_combo.hidePopup()
window.scheme2_color_combo.showPopup()
app.processEvents()
window.scheme2_color_combo.view().window().grab().save(str(output / "color-dropdown.png"))
window.scheme2_color_combo.hidePopup()
scheme2_ui._open_attachment_overlay(window, namespace["AttachmentDialog"], left_scroll)
app.processEvents()
attachment_overlay = window._scheme2_attachment_overlay
attachment_overlay.grab().save(str(output / "attachment-overlay-1366x820.png"))
cabinet_check = attachment_overlay.category_checks["控制柜附件"]
cabinet_combo = attachment_overlay.category_combos["控制柜附件"]
cabinet_check.setChecked(True)
cabinet_combo.setCurrentIndex(cabinet_combo.findText("内门"))
cabinet_combo.showPopup()
app.processEvents()
assert bool(cabinet_combo.property("popupOpen"))
cabinet_combo.view().window().grab().save(str(output / "attachment-dropdown.png"))
cabinet_combo.hidePopup()
attachment_overlay.reject()
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
assert discount_dialog.size() == __import__("PySide6.QtCore").QtCore.QSize(348, 247)
assert discount_dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
assert discount_dialog.discount.text() == "0.85"
assert discount_dialog.preview.text().endswith("元")
assert discount_dialog.findChild(QToolButton, "scheme2DiscountClose") is not None
assert {button.text() for button in discount_dialog.findChildren(QPushButton)} >= {"确定", "取消"}
discount_dialog.grab().save(str(output / "face-discount-dialog.png"))
discount_dialog.close()

attachment_editor = scheme2_ui.AttachmentEditor(window, sample)
attachment_editor.show()
app.processEvents()
attachment_editor.grab().save(str(output / "attachment-editor-dialog.png"))
attachment_editor.close()

long_company_name = "上海智能电气设备制造有限公司"
window.scheme2_company.clear()
window.scheme2_company.addItem(long_company_name)
window.scheme2_company.setCurrentIndex(0)
assert window.scheme2_company.currentText() == long_company_name
assert window.scheme2_company.toolTip() == long_company_name

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
    assert window.scheme2_nav.isVisible() == (width >= 1100)
    assert window.scheme2_compact_coefficients.isVisible() == (width < 1100)

window.close()
print(f"scheme2 UI contract passed; screenshots: {output}")
