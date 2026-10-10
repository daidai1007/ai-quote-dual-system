"""Offline unit-price propagation through the real recovered cost table."""
import copy
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtWidgets import QApplication, QDoubleSpinBox
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline unit-price test')
window = ns['MainWindow']()
base = dict(item_name='固定底座', attachment_price_id=101, quantity=1,
            width_mm=1000, depth_mm=600, height_mm=100, manual_inputs={'底座高度': 100},
            face_price=10, matched_price=10, formula_amount=5, quick_amount=12,
            ganged_fixed_base_match=True, ganged_cabinet_index=0)
other = {**base, 'attachment_price_id': 102, 'width_mm': 800, 'ganged_cabinet_index': 1}
second = {**base, 'quantity': 2, 'formula_amount': 14, 'quick_amount': 30}
window.draft_items = [
    dict(name='并柜', product_code='JP', material_code='SECC', quantity=3,
         ganged_cabinet_count=2, attachments=[base, other], quick_discount=0.5,
         quick={'base_price': 100, 'attachment_fee': 24, 'total_cost': 124}),
    dict(name='单柜', product_code='JS', material_code='SUS304', quantity=2,
         attachments=[second], quick_discount=0.8,
         quick={'base_price': 200, 'attachment_fee': 30, 'total_cost': 230}),
    dict(name='无附件', product_code='JA', quantity=1, attachments=[],
         quick={'total_cost': 300}, quick_discount=1),
]
for item in window.draft_items:
    item['formula'] = {'attachment_fee': 10, 'total_cost': 80}
    item['attachment_confirmation_inputs'] = [{'attachment_price_id': 101, 'quantity': 1}]
window.refresh_summary()
before = copy.deepcopy(window.draft_items)
dialog = ui.AttachmentSummaryDialog(window)
assert dialog.table.horizontalHeaderItem(5).text() == '单价'
price = dialog.table.cellWidget(0, 5)
assert isinstance(price, QDoubleSpinBox) and price.value() == 12
price.setValue(20)
for index in (0, 1):
    current = window.draft_items[index]
    row = current['attachments'][0]
    assert row['quick_amount'] == 20 * row['quantity']
    assert row['unit_price_override'] == 20
    assert current['formula'] == before[index]['formula']
    assert current['attachment_confirmation_inputs'] == before[index]['attachment_confirmation_inputs']
    for key in ('attachment_price_id', 'manual_inputs', 'quantity'):
        assert row[key] == before[index]['attachments'][0][key]
assert other == before[0]['attachments'][1]
assert window.draft_items[2] == before[2]
assert window.draft_items[0]['quick']['total_cost'] == 132
assert window.draft_items[1]['quick']['total_cost'] == 240
assert ui._row_values(window.draft_items[0])[16] == 132 * .5 * 3
assert ui._row_values(window.draft_items[1])[16] == 240 * .8 * 2
assert window.summary_table.item(0, 9).text() == '66.00'
assert window.summary_table.item(1, 9).text() == '192.00'
assert dialog.table.item(0, 4).text() == '60.00'
# Same catalogue/spec across a different product/material/cost is linked too.
assert dialog.table.cellWidget(2, 5).value() == 20
assert dialog.table.item(2, 4).text() == '80.00'
for index, expected in ((0, 60), (1, 80)):
    single = ui.AttachmentEditor(window, window.draft_items[index])
    assert single.table.cellWidget(0, single.COL_AMOUNT).value() == expected
    single.reject()
price.setValue(25)
assert window.draft_items[0]['quick']['total_cost'] == 137
assert window.draft_items[1]['quick']['total_cost'] == 250
price.setValue(0)
assert window.draft_items[0]['quick']['total_cost'] == 112
assert window.draft_items[1]['quick']['total_cost'] == 200
assert dialog.table.item(0, 4).text() == '0.00'
dialog.accept()
reopened = ui.AttachmentSummaryDialog(window)
assert reopened.table.cellWidget(0, 5).value() == 0
reopened.reject()

# Custom rows also link across different prices/costs, without a catalogue ID;
# pending dimensions must not become priced through this control.
wood = dict(custom=True, item_name='木托', quantity=3, formula_amount=15, quick_amount=18)
window.draft_items = [
    dict(quantity=2, attachments=[wood], formula={'total_cost': 80},
         quick={'attachment_fee': 18, 'total_cost': 100}),
    dict(quantity=3, ganged_cabinet_count=2,
         attachments=[{**wood, 'quantity': 2, 'formula_amount': 8, 'quick_amount': 16}],
         formula={'total_cost': 90}, quick={'attachment_fee': 16, 'total_cost': 200}),
    dict(quantity=1, attachments=[{**base, 'pending_manual_dimensions': ['深度']}],
         formula={'total_cost': 50}, quick={'total_cost': 60}),
]
window.refresh_summary()
custom_before = copy.deepcopy(window.draft_items)
custom_dialog = ui.AttachmentSummaryDialog(window)
custom_dialog.table.cellWidget(0, 5).setValue(10)
assert custom_dialog.table.item(0, 4).text() == custom_dialog.table.item(1, 4).text() == '60.00'
assert window.draft_items[0]['quick']['total_cost'] == 112
assert window.draft_items[1]['quick']['total_cost'] == 204
assert not custom_dialog.table.cellWidget(2, 5).isEnabled()
assert window.draft_items[2] == custom_before[2]
for index in (0, 1):
    assert window.draft_items[index]['formula'] == custom_before[index]['formula']
    single = ui.AttachmentEditor(window, window.draft_items[index])
    assert single.table.cellWidget(0, single.COL_AMOUNT).value() == 60
    single.reject()
custom_dialog.accept()
window.close()
print('PASS: unit-price x quantity, linked products, quote/attachment dialogs, repeated edits and frozen costs')
