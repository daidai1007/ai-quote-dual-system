"""Actual recovered Qt controller: checks, details, retry and staged export."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
import scheme2_ui as ui
import v3_launcher

app=QApplication.instance() or QApplication([])
ns=v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
Window,Worker,ExportWorker=ns['MainWindow'],ns['ApiWorker'],ns['WorkbookExportWorker']
good=dict(name='JP测试柜',product_code='JP',material_code='SECC',quantity=2,
  specification='800*600*1800',attachments=[dict(item_name='固定底座',attachment_price_id=99,
  quantity=1,status='CALCULATED',formula_amount=20,quick_amount=0)],
  attachment_contract=2,quote_line_id='11111111-1111-4111-8111-111111111111',
  formula={'total_cost':100},quick={'total_cost':200})

def wait(predicate):
    for _ in range(300):
        app.processEvents()
        if predicate():return
        QTest.qWait(5)
    raise AssertionError('document operation did not complete')

class DocumentProgress(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='quote-document-test-',dir=ROOT/'.codex-tmp')
        self.addCleanup(self.folder.cleanup)
        self.requests,self.messages,self.failures=[],[],[]
        self.response_error=None
        original_init=Worker.__init__
        def capture(worker,url,payload,parent=None,*args,**kwargs):
            original_init(worker,url,payload,parent,*args,**kwargs)
            worker.test_url,worker.test_payload=url,copy.deepcopy(payload)
        def start(worker):
            worker.test_running=True
            self.requests.append((worker.test_url,worker.test_payload))
            endpoint=worker.test_url.rsplit('/',1)[-1]
            worker.progress.emit({'stage':'document_request','endpoint':endpoint,'attempt':1})
            def respond():
                worker.test_running=False
                if self.response_error:
                    worker.failed.emit(json.dumps(self.response_error,ensure_ascii=False))
                elif endpoint=='preview-check':
                    worker.succeeded.emit({'valid':True,'checked_items':1,'persisted':False})
                elif endpoint=='confirm-check':
                    worker.succeeded.emit({'confirmed':True,'dry_run':True,'persisted':False})
                elif endpoint=='confirm':
                    worker.succeeded.emit({'confirmed':True,'history_items':1})
                else:
                    self.fail('unexpected offline endpoint: '+endpoint)
                worker.finished.emit()
            QTimer.singleShot(15,respond)
        def export_start(worker):
            worker.test_running=True
            # Generate only a disposable test workbook, never a production output.
            path=Path(worker.output_path)
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('test.txt','offline staged workbook')
            def prepared():
                worker.test_running=False
                worker.succeeded.emit(str(path))
                worker.finished.emit()
            QTimer.singleShot(10,prepared)
        patches=[patch.object(Window,'load_catalogs',lambda self:None),
            patch.object(Window,'refresh_formula_inputs',lambda self,*args:None),
            patch.object(Worker,'__init__',capture),patch.object(Worker,'start',start),
            patch.object(Worker,'isRunning',lambda worker:bool(getattr(worker,'test_running',False))),
            patch.object(ExportWorker,'start',export_start),
            patch.object(ExportWorker,'isRunning',lambda worker:bool(getattr(worker,'test_running',False))),
            patch.object(QFileDialog,'getSaveFileName',lambda *args:(str(Path(self.folder.name)/'result.xlsx'),'')),
            patch.object(QMessageBox,'critical',lambda parent,title,text:self.messages.append(text)),
            patch.object(QMessageBox,'information',lambda *args:None),
            patch.object(ns['QDesktopServices'],'openUrl',lambda *args:False),
            patch.dict(ns,{'application_root':lambda:Path(self.folder.name)})]
        for p in patches:p.start();self.addCleanup(p.stop)
        self.window=Window()
        self.window._scheme2_loading_order=True
        self.window.draft_items=[copy.deepcopy(good)]
        self.window.scheme2_company.setEditText('测试公司')
        self.window.refresh_summary()
        self.controller=self.window._scheme2_document_controller
        self.addCleanup(self.window.close)

    def test_generate_prechecks_without_confirmation_writes(self):
        self.window.show_section(ui.COST_ROUTE)
        self.window.scheme2_cost_generate.click()
        self.assertFalse(self.window.scheme2_cost_generate.isEnabled())
        wait(lambda:not self.controller.busy)
        self.assertEqual(self.window.stack.currentIndex(),ui.QUOTE_ROUTE)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],['preview-check'])
        self.assertFalse((Path(self.folder.name)/'result.xlsx').exists())
        bar=self.controller.widgets['generate'][1]
        self.assertEqual(bar.value(),4)
        self.assertIn('秒',bar.format())

    def test_local_failure_names_attachment_and_never_requests_server(self):
        row=self.window.draft_items[0]['attachments'][0]
        row.update(status='PENDING_MANUAL',pending_manual_dimensions=['底座高度'])
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual(self.requests,[])
        self.assertIn('第1行报价（JP测试柜）的“固定底座”',self.controller.reason)
        self.assertIn('底座高度',self.controller.reason)
        self.assertTrue(self.controller.widgets['generate'][1].property('failed'))
        self.assertEqual(self.window.scheme2_cost_generate.text(),'重试生成')

    def test_server_failure_locator_and_successful_retry(self):
        self.response_error={'message':'附件成本存在错误，不能确认或导出',
            'issues':[{'line_number':1,'product_name':'JP测试柜','attachment_price_id':99,
                       'attachment_name':'固定底座','reason':'人工尺寸 底座高度必须是正数'}]}
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertTrue(self.controller.widgets['generate'][1].property('failed'))
        self.assertEqual(self.controller.issues[0]['attachment_name'],'固定底座')
        selected=[]
        with patch.object(ui.AttachmentEditor,'exec',lambda editor:selected.append(editor.table.currentRow()) or 0):
            self.controller.locate()
        self.assertEqual(selected,[0])
        self.assertEqual(self.window.summary_table.currentRow(),0)
        self.response_error=None
        self.window.scheme2_cost_generate.click()
        wait(lambda:not self.controller.busy)
        self.assertFalse(self.controller.widgets['generate'][1].property('failed'))
        self.assertEqual(self.window.stack.currentIndex(),ui.QUOTE_ROUTE)

    def test_actual_export_orders_preflight_excel_then_commit_and_finishes(self):
        self.controller.export()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],['confirm-check','confirm'])
        self.assertTrue((Path(self.folder.name)/'result.xlsx').is_file())
        self.assertEqual(self.controller.widgets['export'][1].value(),5)
        self.assertEqual(self.messages,[])

    def test_export_failure_keeps_details_and_does_not_confirm(self):
        self.response_error={'message':'第1行报价（JP测试柜）的“固定底座”：缺少底座高度',
            'issues':[{'line_number':1,'attachment_name':'固定底座','reason':'缺少底座高度'}]}
        self.controller.export()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],['confirm-check'])
        self.assertFalse((Path(self.folder.name)/'result.xlsx').exists())
        self.assertEqual(self.window.scheme2_quote_export.text(),'重试导出')
        self.assertTrue(self.controller.widgets['export'][1].property('failed'))

    def test_failed_progress_has_no_layout_overlap_at_narrow_width(self):
        self.window._scheme2_dirty=False
        self.window.resize(1024,700)
        self.window.show_section(ui.COST_ROUTE)
        self.window.show()
        self.controller.begin('generate')
        self.controller.set_stage(3,'服务端预检')
        self.controller.fail(json.dumps({'message':'附件成本存在错误',
            'issues':[{'line_number':1,'product_name':'JP测试柜','attachment_name':'固定底座',
                       'reason':'人工尺寸 底座高度必须是正数'}]},ensure_ascii=False))
        app.processEvents()
        host,bar,locate=self.controller.widgets['generate']
        self.assertTrue(locate.isVisible())
        self.assertFalse(bar.geometry().intersects(locate.geometry()))
        self.assertIn('底座高度',bar.toolTip())
        path=ROOT/'outputs'/'quote-generation-failure.png'
        path.parent.mkdir(exist_ok=True)
        self.assertTrue(host.grab().save(str(path)))
        self.window._scheme2_dirty=False

if __name__=='__main__':unittest.main()
