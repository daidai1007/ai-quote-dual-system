"""Only the cost-page copy button, row data and numbering; no online API."""
import copy
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtWidgets import QApplication
import v3_launcher
import scheme2_ui as ui
from freight_state import FreightState

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline copy test')
window = ns['MainWindow']()
buttons = window.scheme2_cost_action_buttons
assert [button.text() for button in buttons] == ['× 删除', '↑ 上移', '↓ 下移', '复制', '编辑', '返回', '生成报价单']
duplicate = buttons[3]
assert duplicate.objectName() == buttons[2].objectName()
assert duplicate.size() == buttons[2].size()

sample = json.loads((ROOT / 'tests/fixtures/export_formula_cost_detail.json').read_text('utf-8'))['items'][0]
sample.update(name='原柜名称', attachment_contract=2, quote_line_id='offline-snapshot',
              quantity=2, ganged_cabinet_count=2,
              ganged_cabinets=[{'width_mm': 1000}, {'width_mm': 800}],
              scheme2_cost_settings={'waste_factor': 1.2},
              attachments=[{'custom': True, 'name': '木托', 'quantity': 1,
                            'formula_amount': 5, 'quick_amount': 10}],
              attachment_confirmation_inputs=[{'attachment_price_id': 101, 'quantity': 1,
                                               'manual_inputs': {'底座高度': 100}}])
following = copy.deepcopy(sample)
following['name'] = '后续柜'
window.draft_items = [sample, following]
drawing = {'quantity': 2, 'annotations': [{'text': '保留图纸信息'}]}
window._draft_drawing_refs[id(sample)] = (drawing, FreightState('MANUAL', 10, 20))
window.refresh_summary()
window.summary_table.selectRow(0)
before = copy.deepcopy(sample)
duplicate.click()
assert len(window.draft_items) == 3
copied = window.draft_items[1]
assert copied == before and sample == before and copied is not sample
assert window.draft_items[2] is following and window.summary_table.currentRow() == 1
assert [window.summary_table.item(row, 0).text() for row in range(3)] == ['1', '2', '3']
copied_ref = window._draft_drawing_refs[id(copied)]
assert copied_ref == window._draft_drawing_refs[id(sample)] and copied_ref[0] is not drawing
copied['attachments'][0]['quantity'] = 9
copied['ganged_cabinets'][0]['width_mm'] = 500
copied['attachment_confirmation_inputs'][0]['manual_inputs']['底座高度'] = 200
copied['scheme2_cost_settings']['waste_factor'] = 2
copied_ref[0]['annotations'][0]['text'] = '副本修改'
assert sample == before and drawing['annotations'][0]['text'] == '保留图纸信息'

# Last row inserts at the end, while no selection and the total row do nothing.
window.summary_table.selectRow(2)
duplicate.click()
assert len(window.draft_items) == 4 and window.draft_items[-1]['name'] == following['name']
assert [window.summary_table.item(row, 0).text() for row in range(4)] == ['1', '2', '3', '4']
window.summary_table.clearSelection()
window.summary_table.setCurrentCell(-1, -1)
duplicate.click()
assert len(window.draft_items) == 4
window.summary_table.selectRow(4)
duplicate.click()
assert len(window.draft_items) == 4

# Both responsive arrangements keep Copy between Down and Edit.
for compact in (False, True):
    ui._layout_cost_actions(window, compact)
    grid = window.scheme2_cost_action_grid
    assert [grid.itemAtPosition(0, column).widget().text() for column in range(5)] == [
        '× 删除', '↑ 上移', '↓ 下移', '复制', '编辑']
    assert all(grid.indexOf(button) >= 0 for button in buttons)
window.close()
print('PASS: copy position, full independent snapshot/drawing data, insertion, numbering and invalid selection')
