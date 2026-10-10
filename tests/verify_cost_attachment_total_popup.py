"""Focused offline contract for the cost total-row attachment popup."""
import copy
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QAbstractItemView, QSizeGrip, QWidget
from PySide6.QtTest import QTest
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline summary test')
window = ns['MainWindow']()
base = dict(item_name='固定底座', attachment_price_id=101, width_mm=1000,
            depth_mm=600, height_mm=100, quantity=1, face_price=10,
            matched_price=10, quick_amount=12, formula_amount=5,
            ganged_fixed_base_match=True, ganged_cabinet_index=0)
other = {**base, 'attachment_price_id': 102, 'width_mm': 800, 'ganged_cabinet_index': 1}
custom = dict(custom=True, item_name='木托', quantity=2, formula_amount=20, quick_amount=24)
window.draft_items = [
    dict(name='并柜', quantity=3, ganged_cabinet_count=2, attachments=[base, other, custom]),
    dict(name='单柜', quantity=2, attachments=[copy.deepcopy(base)]),
    dict(name='无附件', quantity=1, attachments=[]),
]
for item in window.draft_items:
    item.update(formula={'total_cost': 100}, quick={'total_cost': 200})
window.refresh_summary()
unchanged = copy.deepcopy(window.draft_items)
entry = window.summary_table.item(len(window.draft_items), 5)
assert entry.text() == '4 项 ›', entry.text()
assert entry.font().underline()
window.resize(1500, 900)
window.show_section(3)
window.show()
app.processEvents()
entry = window.summary_table.item(len(window.draft_items), 5)

with patch.object(ui.AttachmentSummaryDialog, 'exec', return_value=0) as opened:
    window.summary_table.scrollToItem(entry)
    QTest.mouseClick(window.summary_table.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.summary_table.visualItemRect(entry).center())
    opened.assert_called_once()
with patch.object(ui.AttachmentEditor, 'exec', return_value=0) as single:
    ui._cost_cell_clicked(window, 0, 5)
    single.assert_called_once()

dialog = ui.AttachmentSummaryDialog(window)
dialog.show()
app.processEvents()
table = dialog.table
assert [table.horizontalHeaderItem(c).text() for c in range(6)] == [
    '名称', '尺寸 / 规格', '数量', '成本', '金额', '单价']
assert table.rowCount() == 3
assert [table.item(0, c).text() for c in range(6)] == [
    '固定底座', '1000×600×100 mm', '5', '25.00', '60.00', '']
assert table.cellWidget(0, 5).value() == 12
assert [table.item(1, c).text() for c in range(1, 5)] == ['800×600×100 mm', '3', '15.00', '36.00']
assert [table.item(2, c).text() for c in range(2, 5)] == ['6', '60.00', '72.00']
assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
assert all(not table.item(r, c).flags() & Qt.ItemFlag.ItemIsEditable
           for r in range(table.rowCount()) for c in range(6))
assert dialog.findChild(QSizeGrip).isVisible()
dialog.resize(950, 500)
app.processEvents()
assert dialog.width() == 950
image_path = ROOT / 'outputs/attachment-total-popup.png'
assert dialog.grab().save(str(image_path))
dialog.accept()
assert window.draft_items == unchanged

# Changing order quantities is reflected on the next open, not accumulated.
window.draft_items[0]['quantity'] = 1
window.refresh_summary()
updated = ui.AttachmentSummaryDialog(window)
assert updated.table.item(0, 2).text() == '3'
assert updated.table.item(0, 3).text() == '15.00'
assert updated.table.item(0, 4).text() == '36.00'
updated.reject()
assert ui._all_attachment_rows([]) == []
assert ui._all_attachment_rows([{'attachments': []}]) == []
# Do not combine different prices or materials just because names match.
mixed = ui._all_attachment_rows([
    {'quantity': 1, 'material_code': 'SECC', 'attachments': [base, {**base, 'formula_amount': 7}]},
    {'quantity': 1, 'material_code': 'SUS304', 'attachments': [base]},
])
assert len(mixed) == 3
pending = ui._all_attachment_rows([{'quantity': 2, 'attachments': [
    {**base, 'pending_manual_dimensions': ['深度']}]}])[0]
assert pending['cost'] == pending['amount'] == pending['unit_price'] == 0 and pending['pending']
window.close()
print('PASS: total-row entry, all rows, dimensions, merged quantities/money, unit-price control and refresh')
