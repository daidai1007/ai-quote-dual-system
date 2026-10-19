"""Real Qt summary -> manual match -> cost page -> frozen quote/export snapshot."""
import copy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline manual match test')
OLD = '11111111-1111-4111-8111-111111111111'
NEW = '22222222-2222-4222-8222-222222222222'


class Worker(QObject):
    succeeded = Signal(dict)
    failed = Signal(str)
    finished = Signal()
    instances = []

    def __init__(self, url, payload, parent):
        super().__init__(parent)
        self.url, self.payload = url, payload
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def complete(self, result):
        self.succeeded.emit(result)
        self.running = False
        self.finished.emit()

    def error(self, message):
        self.failed.emit(message)
        self.running = False
        self.finished.emit()


def match(width=600, depth=250, height=600):
    return dict(reference_width_mm=width, reference_depth_mm=depth, reference_height_mm=height,
                product_code='JA_SINGLE', manual_match=True)


def response(sizes=None, price=600):
    matches = [match(**dict(zip(('width', 'depth', 'height'), values))) for values in (sizes or [(600,250,600)])]
    return dict(source_quote_line_id=OLD, quote_line_id=NEW, attachment_contract=2,
                quick_quote=dict(base_price=price, total_cost=price+20, attachment_fee=20,
                                 match_method='manual_dimension',manual_match=True,
                                 matched_experience=matches[0] if len(matches)==1 else
                                 dict(ganged_cabinet_count=len(matches),items=matches)))


class ManualMatchTests(unittest.TestCase):
    def setUp(self):
        Worker.instances = []
        self.save_patch = patch.object(ui, '_schedule_order_workspace_save', return_value=None)
        self.save_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.window = ns['MainWindow']()
        self.window._scheme2_api_worker_class = Worker
        self.item = dict(name='人工匹配测试',product_code='JA',material_code='SECC',quote_date='2026-10-19',
                         width_mm=590,depth_mm=230,height_mm=600,specification='590*230*600',
                         quantity=3,quick_discount=.8,freight_fee=12,attachment_contract=2,quote_line_id=OLD,
                         pricing_basis=ui.PRICING_BASIS,
                         attachments=[dict(custom=True,item_name='人工附件',quantity=1,
                                           formula_amount=15,quick_amount=85,custom_amount_edited=True,
                                           quick_amount_override=85)],
                         quick=dict(base_price=500,total_cost=585,attachment_fee=85,matched_experience=match()),
                         formula=dict(material_cost=100,auxiliary_cost=10,labor_cost=20,attachment_fee=15,
                                      spray_cost=30,total_cost=185))
        self.window.draft_items = [self.item]
        self.window.refresh_summary()
        self.summary = ui.AttachmentSummaryDialog(self.window)
        self.editors = []

    def tearDown(self):
        for editor in self.editors:
            editor.reject()
        self.summary.close()
        self.window._scheme2_match_close_requested = False
        for worker in list(getattr(self.window, '_scheme2_match_workers', [])):
            worker.running = False
            worker.finished.emit()
        self.window._scheme2_dirty = False
        self.window._quote_scheme_save_timer.stop()
        self.window.close()

    def editor(self):
        editor = ui.MatchedSizeEditor(self.summary,self.item)
        self.editors.append(editor)
        return editor

    def checked_items(self):
        controller=self.window._scheme2_document_controller
        controller.begin('generate')
        try:
            return controller.validate(copy.deepcopy(self.window.draft_items))
        finally:
            controller.end()

    def test_single_left_click_opens_editor_and_total_row_does_not(self):
        table = self.summary.product_table
        self.summary.show()
        app.processEvents()
        with patch.object(ui.MatchedSizeEditor, 'exec', return_value=0) as opened:
            table.scrollToItem(table.item(0,9))
            app.processEvents()
            QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,
                             pos=table.visualItemRect(table.item(0,9)).center())
            self.assertEqual(opened.call_count,1)
            self.summary._edit_matched_size(1,9)
            self.summary._edit_matched_size(0,8)
            self.assertEqual(opened.call_count,1)

    def test_success_updates_cost_page_and_formal_quote_and_export_after_summary_closes(self):
        before = copy.deepcopy(self.item)
        editor = self.editor()
        editor.inputs[0].setText('600×250×600')
        editor.start_reprice()
        worker = Worker.instances[-1]
        self.assertEqual(worker.payload,dict(quote_line_id=OLD,matched_sizes=[dict(width_mm=600,depth_mm=250,height_mm=600)]))
        self.assertTrue(worker.url.endswith('/api/quotes/rematch-quick'))
        self.assertFalse(editor.confirm.isEnabled())
        worker.complete(response())
        self.assertEqual(self.item['quick']['base_price'],600)
        self.assertEqual(self.item['quick']['attachment_fee'],85)
        self.assertEqual(self.item['quick']['total_cost'],685)
        self.assertEqual(self.item['quote_line_id'],NEW)
        for key in ('attachments','formula','width_mm','depth_mm','height_mm','specification','quantity','quick_discount','freight_fee'):
            self.assertEqual(self.item[key],before[key],key)
        self.assertEqual(self.summary.product_table.item(0,9).text(),'600*250*600')
        self.assertEqual(self.summary.product_table.item(0,5).text(),'577.00')
        self.summary.accept()
        self.assertEqual(self.window.summary_table.item(0,ui.HEADERS.index('报价')).text(),'577.00')
        ui._refresh_quote_page(self.window)
        exported = ui._quote_export_items_snapshot(self.window)[0]
        self.assertEqual(exported['quote_line_id'],NEW)
        self.assertEqual(exported['quote_display']['unit_price'],577)
        self.assertEqual(exported['quote_display']['total'],1731)
        self.assertEqual(exported['attachments'],before['attachments'])
        self.assertEqual(json.loads(json.dumps(self.item))['quick']['base_price'],600)
        checked=self.checked_items()[0]
        self.assertEqual(checked['quote_line_id'],NEW)
        self.assertEqual(checked['quote_display']['total'],1731)

    def test_catalogue_manual_amount_and_old_attachment_audit_ids_remain_exportable(self):
        attachment=dict(attachment_price_id=9,attachment_selection_id=77,quote_line_id=OLD,
                        item_name='风机',quantity=1,status='FIXED',manual_inputs={},
                        formula_amount=10,quick_amount=40,quick_amount_override=40,custom_amount_edited=True)
        self.item['attachments'].append(attachment)
        self.window.refresh_summary()
        before=copy.deepcopy(self.item['attachments'])
        editor=self.editor();editor.start_reprice()
        Worker.instances[-1].complete(response())
        checked=self.checked_items()[0]
        self.assertEqual(checked['quote_line_id'],NEW)
        self.assertEqual(checked['attachments'],before)
        self.assertEqual(checked['quote_display']['quick_base_price'],600)

    def test_copied_orders_are_not_repriced_together(self):
        copied = copy.deepcopy(self.item)
        self.window.draft_items.append(copied)
        before = copy.deepcopy(copied)
        editor = self.editor(); editor.start_reprice()
        Worker.instances[-1].complete(response())
        self.assertEqual(copied,before)
        self.assertEqual(copied['quote_line_id'],OLD)

    def test_ganged_each_child_is_editable_and_print_keeps_actual_specs(self):
        self.item.update(ganged_cabinet_count=2,specification='(590+800)*600*2000',
                         ganged_cabinets=[dict(width_mm=590,depth_mm=230,height_mm=600),
                                         dict(width_mm=800,depth_mm=600,height_mm=2000)])
        self.item['quick']['matched_experience'] = dict(items=[match(),match(800,600,2000)])
        editor = self.editor()
        self.assertEqual(len(editor.inputs),2)
        editor.inputs[1].setText('900*600*2000')
        editor.start_reprice()
        Worker.instances[-1].complete(response([(600,250,600),(900,600,2000)],1500))
        self.assertEqual(self.item['quick']['base_price'],1500)
        self.assertEqual(self.item['specification'],'(590+800)*600*2000')
        self.assertIn('柜体2：900*600*2000',self.summary.product_table.item(0,9).text())
        printer=QPrinter();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        document=self.summary._print_document(printer)
        self.assertIn('柜体2：900*600*2000',document.toPlainText())

    def test_invalid_sizes_do_not_send_any_request(self):
        editor = self.editor()
        for text in ('', '800*0*2000', '(800+800)*600*2000', '800;DELETE*600*2000'):
            editor.inputs[0].setText(text); editor.start_reprice()
            self.assertEqual(Worker.instances,[])
            self.assertTrue(editor.status.text())

    def test_failed_or_missing_exact_match_preserves_every_value_and_allows_retry(self):
        before=copy.deepcopy(self.item)
        editor=self.editor();editor.start_reprice()
        Worker.instances[-1].error(json.dumps(dict(message='该尺寸没有完全对应价格')))
        self.assertEqual(self.item,before)
        self.assertTrue(editor.confirm.isEnabled())
        self.assertIn('原报价未修改',editor.status.text())
        editor.start_reprice();Worker.instances[-1].complete(response())
        self.assertEqual(self.item['quote_line_id'],NEW)

    def test_cancel_then_late_success_never_changes_an_order(self):
        before=copy.deepcopy(self.item)
        editor=self.editor();editor.start_reprice();editor.reject()
        Worker.instances[-1].complete(response())
        self.assertEqual(self.item,before)

    def test_edited_or_removed_order_rejects_a_late_result(self):
        for removed in (False,True):
            self.window.draft_items=[self.item]
            editor=self.editor();editor.start_reprice()
            if removed:
                self.window.draft_items=[]
            else:
                self.item['name']='订单已变化'
            before=copy.deepcopy(self.item)
            Worker.instances[-1].complete(response())
            self.assertEqual(self.item,before)
            self.assertTrue(editor.status.text())

    def test_wrong_snapshot_price_or_dimension_is_rejected_without_partial_update(self):
        sizes=[dict(width_mm=600,depth_mm=250,height_mm=600)]
        for result in ({},response([(601,250,600)]),response(price=float('nan')),
                       {**response(), 'quote_line_id':OLD}):
            before=copy.deepcopy(self.item)
            with self.assertRaises(ValueError):
                ui._apply_manual_quick_match(self.window,self.item,result,OLD,sizes)
            self.assertEqual(self.item,before)

    def test_display_failure_rolls_back_the_item_without_detaching_attachment_rows(self):
        before=copy.deepcopy(self.item)
        attachment=self.item['attachments'][0]
        refresh=self.window.refresh_summary
        with patch.object(self.window,'refresh_summary',side_effect=[RuntimeError('display failed'),None]):
            with self.assertRaises(RuntimeError):
                ui._apply_manual_quick_match(self.window,self.item,response(),OLD,
                    [dict(width_mm=600,depth_mm=250,height_mm=600)])
        self.assertEqual(self.item,before)
        self.assertIs(self.item['attachments'][0],attachment)
        refresh()

    def test_legacy_order_and_busy_document_have_safe_guidance(self):
        self.item.pop('quote_line_id')
        editor=self.editor();editor.start_reprice()
        self.assertEqual(Worker.instances,[])
        self.assertIn('重新计算',editor.status.text())
        self.window._scheme2_document_busy=True
        with patch.object(ui.QMessageBox,'warning') as warning:
            self.summary._edit_matched_size(0,9)
            warning.assert_called_once()
        self.window._scheme2_document_busy=False
        self.window._quote_scheme_read_only=True
        with patch.object(ui.QMessageBox,'warning') as warning:
            self.summary._edit_matched_size(0,9)
            self.assertIn('只读',warning.call_args.args[2])
        editor.start_reprice()
        self.assertIn('只读',editor.status.text())
        self.assertEqual(Worker.instances,[])

    def test_main_window_close_waits_for_retained_network_worker(self):
        editor=self.editor();editor.start_reprice()
        self.window.close()
        self.assertTrue(self.window._scheme2_match_close_requested)
        Worker.instances[-1].error('取消后的网络请求结束')
        self.assertFalse(self.window._scheme2_match_workers)
        self.assertFalse(self.window._scheme2_match_close_requested)

    def test_dialog_resize_and_visual_evidence(self):
        screen=SimpleNamespace(availableGeometry=lambda:QRect(0,0,4096,2160))
        with patch.object(type(self.window),'screen',return_value=screen):
            self.item.update(ganged_cabinet_count=2)
            self.item['quick']['matched_experience']=dict(items=[match(),match(800,600,2000)])
            self.summary._refresh_product_table()
            self.summary.resize(1560,720)
            self.summary.show()
            editor=self.editor()
            editor.show()
            self.assertTrue(editor.property('unifiedDialog'))
            self.assertIsNotNone(editor.findChild(QToolButton,'unifiedDialogClose'))
            self.assertEqual(editor.confirm.property('dialogActionRole'),'primary')
            for width in (480,680):
                editor.resize(width,360)
                app.processEvents()
                self.assertTrue(editor.confirm.isVisible())
                for field in editor.inputs:
                    self.assertGreater(field.width(),field.fontMetrics().horizontalAdvance(field.text()))
                position=editor.confirm.mapTo(editor,editor.confirm.rect().bottomRight())
                self.assertLess(position.x(),editor.width())
                self.assertLess(position.y(),editor.height())
            target=ROOT/'.codex-tmp'/f'manual-matched-size-{os.environ.get("QT_SCALE_FACTOR","1")}'
            target.mkdir(parents=True,exist_ok=True)
            self.assertTrue(editor.grab().save(str(target/'editor.png')))
            self.assertTrue(self.summary.grab().save(str(target/'summary.png')))


if __name__ == '__main__':
    unittest.main()
