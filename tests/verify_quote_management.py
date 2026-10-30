"""Real Qt quotation management, synthetic data and offline transport only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import time
import unittest
from unittest.mock import patch, Mock
from urllib.parse import urlparse

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
TEMP = tempfile.TemporaryDirectory(prefix='quote-management-tests-')
os.environ['AI_QUOTE_ORDER_CACHE_ROOT'] = TEMP.name
os.environ['AI_QUOTE_UPDATE_CONFIG'] = str(Path(TEMP.name) / 'updates.json')
Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}', encoding='utf-8')

from PySide6.QtCore import QSettings, Qt, QRect, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
import scheme2_ui as ui
import quote_management as qm
import quote_management_model as model
import quote_scheme_center as centre
import v3_launcher

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, TEMP.name)
APP = QApplication.instance() or QApplication([])
NS = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
NS['install_application_font'](APP)
NS['MainWindow'].load_catalogs = lambda self: None


def items():
    return [dict(name='测试控制柜', product_code='JQ_EXP', specification='1000*480*1060', quantity=3,
                 quick_discount=.9, freight_fee=10,
                 quick=dict(base_price=1000, attachment_fee=170, total_cost=1170),
                 formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20,
                              attachment_fee=60, spray_cost=10, total_cost=200),
                 attachments=[dict(item_name='安装板', category_level1='安装板', quantity=1,
                                   quick_amount=120, formula_amount=50),
                              dict(item_name='锁定附件', category_level1='其他附件', quantity=1,
                                   quick_amount=50, formula_amount=10)]),
            dict(name='测试壁挂箱', product_code='JE_SINGLE', specification='600*300*800', quantity=2,
                 quick_discount=.8, quick=dict(base_price=500, attachment_fee=0, total_cost=500),
                 formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20,
                              attachment_fee=0, spray_cost=10, total_cost=140), attachments=[])]


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate(): return
        QTest.qWait(10)
    raise AssertionError('Offline Qt state timed out')


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.requests = []; self.saved = None
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden in tests'))
        self.network.start()
        def run(worker):
            path = urlparse(worker.url).path
            self.requests.append((worker.method, path, deepcopy(worker.payload)))
            if worker.method == 'GET' and path.endswith('/quote-schemes'):
                result = dict(items=[dict(scheme_no='BJ-20261021-000001', company_name='测试客户',
                    status='QUOTED', order_nature='EXTERNAL', quoted_amount=4004, version_no=1, lock_version=1)], total=1)
            elif worker.method == 'PUT':
                self.saved = deepcopy(worker.payload['snapshot'])
                result = dict(saved=True, lock_version=worker.payload['expected_version']+1)
            elif worker.method == 'GET':
                result = dict(found=True, scheme_no='BJ-20261021-000001', status='DRAFT', lock_version=2,
                              version_no=1, snapshot=deepcopy(self.saved), quote_management_historical_export=True)
            else:
                worker.failed.emit('Unexpected offline write'); return
            worker.succeeded.emit(result)
        self.worker_patch = patch.object(centre.QuoteSchemeWorker, 'run', run); self.worker_patch.start()
        screen = Mock(wraps=APP.primaryScreen()); screen.availableGeometry.return_value = QRect(0,0,4096,2160)
        self.screen_patch = patch.object(NS['MainWindow'], 'screen', return_value=screen); self.screen_patch.start()
        self.window = NS['MainWindow'](); self.w = self.window
        self.w._quote_order_nature = 'EXTERNAL'
        self.w.quote_scheme_operator_name.setText('测试操作人')
        self.w._quote_scheme_loading = True
        self.w._quote_scheme_id = 'BJ-20261021-000001'; self.w._quote_scheme_version = 1
        self.w._quote_scheme_status = 'DRAFT'; self.w.draft_items = items()
        self.w.scheme2_company.setCurrentText('测试客户')
        self.w._quote_scheme_loading = False
        self.w.refresh_summary(); self.w._quote_scheme_save_timer.stop()
        self.w._quote_scheme_dirty_seq = self.w._quote_scheme_saved_seq = 0
        self.m = self.w.quote_management; self.m.generated(); self.w.show_section(2)
        self.w.resize(1280, 860); self.w.show(); APP.processEvents()

    def tearDown(self):
        wait(lambda: not self.w._quote_scheme_workers)
        self.w._quote_scheme_save_timer.stop(); self.w._quote_scheme_id = ''
        self.w._scheme2_dirty = False; self.w.close(); self.w.deleteLater(); APP.processEvents()
        self.worker_patch.stop(); self.network.stop(); self.screen_patch.stop()

    def test_columns_and_direct_price_discount_math(self):
        d = qm.AdjustQuoteDialog(self.w.draft_items, 2, self.w)
        self.assertEqual(tuple(d.grid.horizontalHeaderItem(i).text() for i in range(6)), qm.AdjustQuoteDialog.HEADERS)
        self.assertEqual(d.grid.item(0, 4).text(), '0.9'); self.assertEqual(d.grid.item(1, 4).text(), '0.8')
        d.grid.item(0, 2).setText('1100.01')
        self.assertEqual(d.grid.item(0, 3).text(), '3,300.03')
        self.assertEqual(ui._row_values(d.items[0])[15], 1100.01)
        self.assertIn('4,100.03', d.total.text())
        d.grid.item(0, 5).setText('0.85')
        self.assertEqual(d.grid.item(0, 2).text(), '1012.00')
        self.assertIn('3,836.00', d.total.text())
        model.attachment_unit_price(d.items[0], 0, '100')
        self.assertEqual(ui._row_values(d.items[0])[15], 995)
        with self.assertRaises(ValueError): model.attachment_unit_price(d.items[0], 1, '1')
        self.assertEqual(d.items[0]['attachments'][1]['quick_amount'], 50)
        d.grid.item(0, 2).setText('59.99'); self.assertTrue(d.errors)
        d.grid.item(0, 2).setText('1100.01'); self.assertFalse(d.errors)
        d.grid.item(1, 5).setText('nan'); self.assertTrue(d.errors)
        d.reject()

    def test_actual_page_review_save_cancel_and_inline_attachments(self):
        def edit_page():
            d = self.m.root.currentWidget()
            self.assertIsInstance(d,qm.AdjustQuoteDialog)
            self.assertNotIsInstance(d,QDialog)
            d.accept(); self.assertFalse(d.reviewing)
            self.assertIn('调价原因',d.error.text())
            editor=d.inputs[0,2]; editor.setFocus(); editor.selectAll(); QTest.keyClicks(editor,'1100.01')
            self.assertEqual(d.grid.item(0,3).text(),'3,300.03')
            d.attachment_row(0)
            self.assertTrue(d.attachment_panel.isVisible())
            from PySide6.QtWidgets import QLineEdit, QTableWidget
            attachment_grid=d.attachment_panel.findChild(QTableWidget)
            self.assertFalse(attachment_grid.cellWidget(0,2).isReadOnly())
            self.assertTrue(attachment_grid.cellWidget(1,2).isReadOnly())
            d.attachment_panel.hide(); d.reason.setPlainText('实际页面调价测试')
            d.accept(); self.assertTrue(d.reviewing); self.assertTrue(d.grid.isHidden())
            self.assertEqual(d.primary.text(),'确认保存 V2')
            d.back(); self.assertFalse(d.reviewing)
            d.accept(); d.accept()
        QTimer.singleShot(0,edit_page); self.m.adjust()
        wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(len(self.m.state['versions']),2)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15],1100.01)
        before=deepcopy(self.m.state)
        QTimer.singleShot(0,lambda:self.m.root.currentWidget().reject()); self.m.adjust()
        self.assertEqual([v['amount'] for v in self.m.state['versions']],[v['amount'] for v in before['versions']])

    def test_real_window_visual_states(self):
        output = ROOT / 'outputs' / 'quote-management-qa' / os.environ.get('QT_SCALE_FACTOR', '1')
        output.mkdir(parents=True, exist_ok=True)
        self.w.grab().save(str(output / 'quote-document.png'))
        d = qm.AdjustQuoteDialog(self.w.draft_items, 2, self.w)
        self.m.root.addWidget(d); d.setWindowFlags(Qt.WindowType.Widget); self.m.root.setCurrentWidget(d)
        d.show(); APP.processEvents()
        self.w.grab().save(str(output / 'quote-adjust.png'))
        d.attachment_row(0); APP.processEvents(); self.w.grab().save(str(output/'quote-attachments.png'))
        d.attachment_panel.hide(); d.reason.setPlainText('测试议价'); d.accept(); APP.processEvents()
        self.w.grab().save(str(output/'quote-review.png')); d.back()
        self.w.resize(1024,768); APP.processEvents()
        self.w.grab().save(str(output/'quote-adjust-1024.png'))
        self.assertTrue(d.primary.isVisibleTo(self.w))
        self.assertTrue(self.w.rect().contains(d.primary.mapTo(self.w,d.primary.rect().bottomRight())))
        self.w.resize(1280,860); d.reject()
        self.m.root.setCurrentWidget(self.m.detail_page); self.m.root.removeWidget(d)
        self.m.show_list(); wait(lambda: self.m.list_table.rowCount() == 1)
        self.m.list_table.selectRow(0); APP.processEvents()
        self.w.grab().save(str(output / 'quote-list.png'))
        self.assertFalse(self.w.scheme2_action_dock.isVisibleTo(self.w))

    def make_adjustment(self):
        def accept(dialog):
            dialog.grid.item(0, 2).setText('1100.01')
            dialog.reason.setPlainText('测试议价')
            return QDialog.DialogCode.Accepted
        with patch.object(qm.AdjustQuoteDialog, 'exec', accept): self.m.adjust()
        wait(lambda: self.w._quote_scheme_save_worker is None)
        self.w._quote_scheme_save_timer.stop()

    def test_save_reopen_history_print_and_export_snapshots(self):
        self.make_adjustment()
        self.assertEqual(len(self.m.state['versions']), 2)
        self.assertEqual(self.saved['quote_management']['current'], 2)
        self.assertEqual(self.saved['quote_management']['versions'][0]['amount'], 4004)
        self.assertEqual(self.saved['quote_management']['versions'][1]['amount'], 4100.03)
        exported = ui._quote_export_items_snapshot(self.w)
        self.assertEqual(exported[0]['quote_display']['unit_price'], 1100.01)
        self.assertEqual(exported[0]['quote_display']['total'], 3300.03)
        self.assertIn('3,300.03', ui._printable_quote_html(self.w))
        saved = deepcopy(self.saved)
        centre._apply_opened_scheme(self.w, dict(scheme_no=self.w._quote_scheme_id, status='DRAFT',
            lock_version=2, version_no=1, snapshot=saved, quote_management_historical_export=True), 2)
        self.assertIs(self.m.root.currentWidget(), self.m.detail_page)
        self.assertEqual(self.m.tabs.currentIndex(), 0)
        self.m.view_version(1)
        self.assertTrue(self.w._quote_scheme_read_only)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15], 1068)
        self.assertIn('3,204.00', ui._printable_quote_html(self.w))
        self.assertEqual(ui._order_workspace_payload(self.w)['draft_items'][0]['quick_discount'], saved['draft_items'][0]['quick_discount'])
        self.assertTrue(centre._prepare_export(self.w))
        receipt = self.w._quote_scheme_export_context
        self.assertEqual(receipt['payload']['historical_quote_version'], 1)
        self.assertEqual(receipt['payload']['snapshot']['company'], '测试客户')
        self.assertEqual(receipt['payload']['snapshot']['draft_items'][0]['quick_discount'], .9)
        self.assertEqual(receipt['payload']['snapshot']['quote_management']['current'], 2)
        centre._release_export(self.w)
        self.m.restore_latest()
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15], 1100.01)
        self.assertFalse(self.w._quote_scheme_read_only)
        self.w._quote_scheme_save_timer.stop()

    def test_list_contract_entry_and_scheme_return(self):
        self.saved = centre._snapshot(self.w)
        self.m.show_list(); wait(lambda: self.m.list_table.rowCount() == 1)
        self.assertFalse(self.m.contract_button.isEnabled())
        self.m.list_table.selectRow(0); self.assertTrue(self.m.contract_button.isEnabled())
        self.m.contract_button.click()
        self.assertEqual(self.w.stack.currentIndex(), self.m.contract_route)
        self.assertIn('BJ-20261021-000001', self.m.contract_source.text())
        # The real contract page protects navigation while its bootstrap is active.
        page = self.w.contract_management
        wait(lambda: not page.busy and not page.workers and not page.queue)
        centre._open_scheme(self.w, 'BJ-20261021-000001', 2)
        wait(lambda: self.w.stack.currentIndex() == 2 and self.m.root.currentWidget() == self.m.detail_page)
        self.assertEqual(self.m.tabs.currentIndex(), 0)
        self.assertEqual([b.text() for b in self.w.nav_buttons], ['选型配置','成本计算','报价单管理','合同管理','报价方案','报价分析'])

    def test_adjustment_uses_original_real_xlsx_renderer(self):
        self.make_adjustment()
        with tempfile.TemporaryDirectory(prefix='qm-xlsx-') as folder:
            source,output=Path(folder)/'synthetic.json',Path(folder)/'synthetic.xlsx'
            source.write_text(json.dumps(dict(items=ui._quote_export_items_snapshot(self.w),
                company_name='测试客户',quote_date='2026-10-21'),ensure_ascii=False),encoding='utf-8')
            rendered=subprocess.run(['node',str(ROOT/'export_dual_quote_workbook.mjs'),str(source),str(output)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(rendered.returncode,0,rendered.stderr)
            with ZipFile(output) as book:
                self.assertIsNone(book.testzip())
                ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                document=ET.fromstring(book.read('xl/workbook.xml'))
                quick=next(s for s in document.findall('s:sheets/s:sheet',ns) if s.get('name')=='报价')
                rel=quick.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                relations=ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
                target=next(r.get('Target') for r in relations if r.get('Id')==rel)
                sheet=ET.fromstring(book.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target))
                values={c.get('r'):c.findtext('s:v',namespaces=ns) for c in sheet.findall('.//s:c',ns)}
                self.assertEqual(float(values['F11']),1100.01)
                self.assertEqual(float(values['G11']),3300.03)
                self.assertEqual(float(values['F12']),400)
                self.assertEqual(float(values['G12']),800)


if __name__ == '__main__': unittest.main()
