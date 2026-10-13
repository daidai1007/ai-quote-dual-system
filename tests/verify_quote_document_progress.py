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
import attachment_v2_client as v2
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
                elif endpoint in ('recalculate-line','preview'):
                    costs=[dict(selection, item_name='安装板' if selection['attachment_price_id']==1 else
                        '分段板' if '分段板高度' in selection['manual_inputs'] else '玻璃门', status='CALCULATED',
                        formula_unit_cost=8.8,formula_amount=8.8*selection['quantity']*selection.get('attachment_price_sign',1),
                        quick_amount=250.26*selection['quantity']*selection.get('attachment_price_sign',1))
                        for selection in worker.test_payload['attachments']]
                    worker.succeeded.emit(dict(attachments=costs,attachment_contract=2,
                        quote_line_id='22222222-2222-4222-8222-222222222222',
                        formula_cost={'total_cost':158.8}))
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

    def snapshot_queue(self, count=5):
        self.window.draft_items = [dict(copy.deepcopy(good), name=f'柜{index+1}',
            attachment_snapshot_dirty=True) for index in range(count)]
        requests, ready = [], []
        self.window.refresh_draft_attachment_snapshot = lambda item, succeeded, failed: requests.append(
            (item, succeeded, failed))
        self.controller.begin('generate')
        self.controller.prepare_snapshots(lambda: (ready.append(True), self.controller.end()))
        return requests, ready

    def test_snapshot_updates_two_at_a_time_and_waits_for_every_row(self):
        requests, ready = self.snapshot_queue()
        self.assertEqual(len(requests), 2)
        self.assertIn('已完成 0/5 行', self.controller.label)
        requests[1][1]()
        self.assertEqual(len(requests), 3)
        self.assertIn('已完成 1/5 行', self.controller.label)
        self.window._scheme2_dirty=False
        self.window.resize(1560,900)
        self.window.show_section(ui.COST_ROUTE)
        self.window.show()
        app.processEvents()
        host,bar,_locate=self.controller.widgets['generate']
        self.assertIn('已完成 1/5 行',bar.toolTip())
        self.assertTrue(host.grab().save(str(ROOT/'outputs/quote-snapshot-concurrent-progress.png')))
        requests[0][1]()
        self.assertEqual(len(requests), 4)
        requests[3][1]()
        self.assertEqual(len(requests), 5)
        requests[4][1]()
        self.assertEqual(ready, [])
        requests[2][1]()
        self.assertEqual(ready, [True])
        self.assertIn('已完成 5/5 行', self.controller.label)
        requests[2][1]()  # A duplicated callback must not start precheck twice.
        self.assertEqual(ready, [True])

    def test_snapshot_failure_stops_new_rows_drains_active_and_keeps_locator(self):
        requests, ready = self.snapshot_queue()
        requests[1][2](json.dumps({'message':'玻璃门尺寸无效', 'issues':[
            {'attachment_name':'玻璃门','attachment_price_id':1192,'reason':'高度必须是正数'}]},ensure_ascii=False))
        self.assertTrue(self.controller.busy, 'do not permit retry while the other request is in flight')
        self.assertEqual(len(requests), 2)
        requests[0][1]()
        self.assertFalse(self.controller.busy)
        self.assertEqual(len(requests), 2)
        self.assertEqual(ready, [])
        self.assertEqual(self.controller.issues[0]['line_number'], 2)
        self.assertEqual(self.controller.issues[0]['product_name'], '柜2')
        self.assertIn('高度必须是正数', self.controller.reason)
        self.assertNotIn('第?行', self.controller.reason)
        self.controller.begin('generate')
        requests[1][2]('过期失败')
        self.assertTrue(self.controller.busy)
        self.assertEqual(self.controller.reason, '')
        self.controller.end()

    def test_parallel_real_refresh_preserves_each_copy_manual_price_and_custom_rows(self):
        item,row=self.edited_glass()
        self.window.draft_items=[dict(copy.deepcopy(item),name=f'复制柜{i+1}',quantity=i+1) for i in range(4)]
        first=self.window.draft_items[0]
        first['attachments'][0].update(quick_amount=0,quick_amount_override=0,custom_amount_edited=True)
        temporary=dict(custom=True,item_name='临时附件',quantity=1,formula_amount=5,quick_amount=6,
            quick_amount_override=6,custom_amount_edited=True)
        first['attachments'].append(temporary)
        first['quick']={'total_cost':506,'attachment_fee':6}
        first['formula']={'total_cost':163.8,'attachment_fee':13.8}
        started=[]
        original=Worker.start
        def track(worker):
            original(worker)
            if worker.test_url.endswith('/recalculate-line'):
                started.append(worker)
                self.assertLessEqual(sum(candidate.test_running for candidate in started),2)
        with patch.object(Worker,'start',track):
            self.controller.generate()
            wait(lambda:not self.controller.busy)
        self.assertEqual(len(started),4)
        self.assertEqual(self.requests[-1][0].rsplit('/',1)[-1],'preview-check')
        self.assertEqual(first['attachments'][0]['quick_amount'],0)
        self.assertEqual(first['attachments'][1],temporary)
        self.assertEqual(first['quick']['total_cost'],506)
        self.assertEqual([copy['quantity'] for copy in self.window.draft_items],[1,2,3,4])
        self.assertTrue(all(not v2.attachment_snapshot_needs_refresh(copy) for copy in self.window.draft_items))
        self.assertEqual(self.controller.reason,'')

    def test_unchanged_rows_retain_snapshots_without_extra_requests(self):
        self.window.draft_items *= 4
        ready=[]
        self.controller.begin('generate')
        self.controller.prepare_snapshots(lambda: ready.append(True))
        self.assertEqual(ready,[True])
        self.assertEqual(self.requests,[])
        self.controller.end()

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

    def edited_glass(self):
        item=self.window.draft_items[0]
        row=dict(item_name='玻璃门',attachment_price_id=1192,quantity=1,status='CALCULATED',
            formula_amount=8.8,quick_amount=250.26,
            manual_inputs={'玻璃门宽度':400,'玻璃门高度':400})
        item['attachments']=[row]
        item['attachment_confirmation_inputs']=v2.confirmation_inputs([{**row,'manual_inputs':{}}])
        item['formula']={'total_cost':158.8,'attachment_fee':8.8}
        item['quick']={'total_cost':750.26,'attachment_fee':250.26}
        return item,row

    def test_generate_replaces_stale_glass_snapshot_before_precheck(self):
        item,row=self.edited_glass()
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],
                         ['recalculate-line','preview-check'])
        self.assertEqual(self.requests[0][1]['attachments'][0]['manual_inputs'],row['manual_inputs'])
        self.assertEqual(item['quote_line_id'],'22222222-2222-4222-8222-222222222222')
        checked=self.requests[1][1]['items'][0]
        self.assertEqual(checked['quote_line_id'],item['quote_line_id'])
        self.assertEqual(checked['attachments'][0]['manual_inputs'],row['manual_inputs'])
        self.assertEqual(self.window.stack.currentIndex(),ui.QUOTE_ROUTE)
        self.assertFalse(v2.attachment_snapshot_needs_refresh(item))

    def test_snapshot_refresh_preserves_manual_zero_and_temporary_attachment(self):
        item,row=self.edited_glass()
        row.update(quick_amount=0,quick_amount_override=0,custom_amount_edited=True)
        temporary=dict(custom=True,item_name='临时附件',quantity=1,formula_amount=5,
                       quick_amount=6,quick_amount_override=6,custom_amount_edited=True)
        item['attachments'].append(copy.deepcopy(temporary))
        item['quick']={'total_cost':506,'attachment_fee':6}
        item['formula']={'total_cost':163.8,'attachment_fee':13.8}
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual(item['attachments'][0]['quick_amount'],0)
        self.assertEqual(item['attachments'][1],temporary)
        self.assertEqual(len(self.requests[0][1]['attachments']),1)
        self.assertEqual(item['quick']['total_cost'],506)
        self.assertEqual(item['formula']['total_cost'],163.8)
        self.assertEqual(item['quantity'],2)

    def test_export_refreshes_snapshot_before_preflight_and_commit(self):
        item,row=self.edited_glass()
        self.controller.export()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],
                         ['recalculate-line','confirm-check','confirm'])
        self.assertTrue((Path(self.folder.name)/'result.xlsx').is_file())
        for _url,payload in self.requests[1:]:
            self.assertEqual(payload['items'][0]['quote_line_id'],item['quote_line_id'])
        self.assertEqual(self.messages,[])

    def test_refresh_error_preserves_old_snapshot_and_attachment_locator(self):
        item,row=self.edited_glass()
        old=copy.deepcopy(item)
        self.response_error={'message':'玻璃门尺寸无效','issues':[
            {'attachment_name':'玻璃门','attachment_price_id':1192,'reason':'高度必须是正数'}]}
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],['recalculate-line'])
        self.assertEqual(item,old)
        self.assertEqual(self.controller.issues[0]['line_number'],1)
        self.assertEqual(self.controller.issues[0]['attachment_price_id'],1192)
        self.assertTrue(self.controller.widgets['generate'][1].property('failed'))

    def test_model_change_refreshes_id_but_price_only_edit_does_not(self):
        item,row=self.edited_glass()
        item['attachment_confirmation_inputs']=v2.confirmation_inputs(item['attachments'])
        row.update(quick_amount_override=0,custom_amount_edited=True)
        self.assertFalse(v2.attachment_snapshot_needs_refresh(item))
        row['attachment_price_id']=1178
        self.assertTrue(v2.attachment_snapshot_needs_refresh(item))
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual(self.requests[0][1]['attachments'][0]['attachment_price_id'],1178)
        self.assertEqual(item['attachment_confirmation_inputs'][0]['attachment_price_id'],1178)

    def test_segment_board_popup_height_edit_refreshes_snapshot_before_generate(self):
        item=self.window.draft_items[0]
        row=dict(item_name='分段板',category_level1='安装附件',attachment_price_id=29,
                 quantity=1,status='PENDING_MANUAL',manual_inputs={},
                 pending_manual_dimensions=['分段板高度'],
                 required_parameters=[{'name':'分段板高度','source':'MANUAL'}],
                 formula_amount=0,quick_amount=0)
        item['attachments']=[row]
        item['attachment_confirmation_inputs']=v2.confirmation_inputs(item['attachments'])
        old_inputs=copy.deepcopy(item['attachment_confirmation_inputs'])
        editor=ui.AttachmentEditor(self.window,item)
        self.addCleanup(editor.close)
        source={**row,'manual_inputs':{'分段板高度':150}}
        editor._reprice_row(0,source,editor.table.item(0,editor.COL_SPECIFICATION))
        wait(lambda:editor.table.cellWidget(0,editor.COL_AMOUNT).isEnabled())
        editor.accept()
        self.assertTrue(item['attachment_snapshot_dirty'])
        self.assertEqual(item['attachment_confirmation_inputs'],old_inputs)
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],
                         ['preview','recalculate-line','preview-check'])
        checked=self.requests[-1][1]['items'][0]
        self.assertEqual(checked['attachments'][0]['manual_inputs'],{'分段板高度':150})
        self.assertEqual(checked['quote_line_id'],'22222222-2222-4222-8222-222222222222')
        self.assertFalse(v2.attachment_snapshot_needs_refresh(item))

    def test_negative_board_quantity_recalculates_and_generates_with_deduction_contract(self):
        item,row=self.edited_glass()
        row.update(item_name='安装板',category_level1='安装板',attachment_price_id=1,
                   formula_unit_cost=8.8,manual_inputs={})
        item['quick']['total_cost']=1250.26
        item['attachment_confirmation_inputs']=v2.confirmation_inputs([row])
        editor=ui.AttachmentEditor(self.window,item)
        self.addCleanup(editor.close)
        editor.table.cellWidget(0,editor.COL_QUANTITY).setValue(-4)
        editor.accept()
        self.controller.generate()
        wait(lambda:not self.controller.busy)
        self.assertEqual([url.rsplit('/',1)[-1] for url,_ in self.requests],
                         ['recalculate-line','preview-check'])
        for payload in (self.requests[0][1],self.requests[1][1]['items'][0]):
            selected=payload['attachments'][0]
            self.assertEqual(selected['quantity'],2)
            self.assertEqual(selected['attachment_price_sign'],-1)
        self.assertEqual(item['attachments'][0]['formula_amount'],-17.6)
        self.assertEqual(item['attachments'][0]['quick_amount'],-500.52)
        self.assertEqual(item['quick']['total_cost'],499.48)
        self.assertEqual(self.window.stack.currentIndex(),ui.QUOTE_ROUTE)
        self.assertFalse(v2.attachment_snapshot_needs_refresh(item))

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
