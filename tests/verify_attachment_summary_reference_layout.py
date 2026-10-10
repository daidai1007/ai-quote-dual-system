"""Reference layout: product quotes/breakdown above linked attachment detail."""
import copy
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QSplitter
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline reference layout test')
window = ns['MainWindow']()
base = dict(item_name='固定底座', attachment_price_id=101, width_mm=1000,
            depth_mm=600, height_mm=100, quantity=1, formula_amount=25, quick_amount=50,
            matched_price=50, ganged_fixed_base_match=True, ganged_cabinet_index=0)
other_base = {**base, 'attachment_price_id': 102, 'width_mm': 800,
              'formula_amount': 20, 'quick_amount': 40, 'ganged_cabinet_index': 1}
wood = dict(custom=True, item_name='木托', quantity=1, formula_amount=10, quick_amount=20)
wire = dict(item_name='接地线-编织带', attachment_price_id=103, quantity=2,
            formula_amount=12, quick_amount=30)
window.draft_items = [
    dict(name='JP', product_code='JP', specification='(1000+800)*600*(1800+100)',
         material_code='SECC', quantity=3, ganged_cabinet_count=2,
         attachments=[base, other_base, wood, wire],
         quick={'attachment_fee': 140, 'total_cost': 500},
         formula={'attachment_fee': 67, 'total_cost': 300},
         freight_fee=10, quick_discount=.5),
    dict(name='未命名', product_code='JA', specification='480*300*210', quantity=2,
         attachments=[], quick={'attachment_fee': 0, 'total_cost': 200},
         formula={'total_cost': 150}, freight_fee=4, quick_discount=.8),
]
window.refresh_summary()
before = copy.deepcopy(window.draft_items)
dialog = ui.AttachmentSummaryDialog(window)
assert hasattr(dialog, 'product_table'), 'reference requires a product quote table above the attachment detail'
products = dialog.product_table
assert [products.horizontalHeaderItem(c).text() for c in range(products.columnCount())] == [
    '序号', '名称', '规格型号(W*D*H)', '数量', '单位', '折后单价', '折后总价',
    '原价单价', '折后单价', '柜体', '固定底座', '木托', '其他附件/差额', '运费', '折扣']
assert products.rowCount() == 3
assert [products.item(0, c).text().replace('\n', '') for c in range(7)] == [
    '1', 'JP', '(1000+800)*600*(1800+100)', '3', '台', '255.00', '765.00']
assert [products.item(0, c).text() for c in range(7, 15)] == [
    '510.00', '255.00', '180.00', '45.00', '10.00', '15.00', '5.00', '0.50']
assert products.item(1, 5).text() == '163.20' and products.item(1, 6).text() == '326.40'
assert products.item(2, 1).text() == '合计' and products.item(2, 6).text() == '1,091.40'
assert all(not products.item(r, c).flags() & Qt.ItemFlag.ItemIsEditable
           for r in range(products.rowCount()) for c in range(products.columnCount()))
assert dialog.findChild(QLabel, 'scheme2AttachmentSummaryDetailsTitle').text() == '附件明细'
assert dialog.findChild(QSplitter).orientation() == Qt.Orientation.Vertical
assert dialog.table.item(0, 1).text() == '1000×600×100 mm'
assert dialog.table.item(1, 1).text() == '800×600×100 mm'
assert dialog.table.item(0, 2).text() == dialog.table.item(1, 2).text() == '3'
assert window.draft_items == before
dialog.table.cellWidget(0, 5).setValue(70)
assert products.item(0, 5).text() == '265.00'
assert products.item(0, 6).text() == '795.00'
assert products.item(0, 9).text() == '180.00'
assert products.item(0, 10).text() == '55.00'
assert products.item(1, 5).text() == '163.20'
assert products.item(2, 6).text() == '1,121.40'
assert dialog.table.item(0, 4).text() == '210.00'
assert window.summary_table.item(0, 9).text() == '265.00'
assert window.draft_items[0]['formula'] == before[0]['formula']
# The fee audit must always reconcile to the current cost-table quote.
for row, item in enumerate(window.draft_items):
    values = ui._attachment_summary_product_values(item, row + 1)
    assert abs(sum(values[9:14]) - values[5]) < .000001
    assert values[5] == ui._row_values(item)[15]
    assert values[6] == ui._row_values(item)[16]
sus = copy.deepcopy(window.draft_items[1])
sus.update(material_code='SUS316', scheme2_cost_settings={'material_difference': 2.5})
sus['formula']['corrected_material_weight_kg'] = 10
values = ui._attachment_summary_product_values(sus, 1)
assert values[12] == 25 and abs(values[5] - 188.2) < .000001
assert abs(sum(values[9:14]) - values[5]) < .000001
dialog.resize(1560, 720)
dialog.show()
app.processEvents()
assert products.mapTo(dialog, products.rect().bottomLeft()).y() < dialog.table.mapTo(dialog, dialog.table.rect().topLeft()).y()
assert dialog.grab().save(str(ROOT / 'outputs/attachment-summary-reference-layout.png'))
dialog.accept()
window.draft_items = []
empty = ui.AttachmentSummaryDialog(window)
assert empty.product_table.rowCount() == 1 and empty.table.rowCount() == 0
empty.close()
window.close()
print('PASS: reference two-section layout, product fee audit, separate ganged bases, live price/quote updates, SUS316 difference and empty list')
