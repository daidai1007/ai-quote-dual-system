"""Actual detail button -> named loopback API -> formal snapshot -> Office.
The first quote is never adjusted, revised, printed or exported beforehand.
"""
from copy import deepcopy
from hashlib import sha256
import json,os,unittest,urllib.request
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import verify_contract_management as base
import quote_scheme_center as schemes
import quote_management_model as model
import contract_management as contracts
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QCloseEvent

def product(price=200):
    return dict(name='本机直接合同产品',product_code='JE_SINGLE',specification='600*300*800',quantity=2,quick_discount=1,freight_fee=0,
      quick=dict(base_price=price,attachment_fee=0,total_cost=price),
      formula=dict(material_cost=20,auxiliary_cost=5,labor_cost=10,attachment_fee=0,spray_cost=5,management_fee=2,total_cost=42),attachments=[])

class DetailContractTests(unittest.TestCase):
    setUpClass=classmethod(base.ContractTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ContractTests.tearDownClass.__func__)
    api=base.ContractTests.api;settled=base.ContractTests.settled;close_window=base.ContractTests.close_window
    configure_template=base.ContractTests.configure_template
    def setUp(self):
        base.ContractTests.setUp(self);self.m=self.w.quote_management;self.c=self.m.detail_contract_controller

    def quote_api(self,path,payload=None):
        request=urllib.request.Request(self.config['base']+'/api/quote-schemes'+path,
          data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),
          headers={'X-AI-Quote-Key':self.config['key'],'Authorization':'Bearer '+self.config['session']['token'],'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)

    def open_draft(self,nature='EXTERNAL',number=1):
        rows=[product()];state=model.restore_state(None)
        for i in range(number):model.append_version(state,rows,'本机测试客户 A','本机合成调价记录',self.config['session']['person']['display_name'],'2026-10-29',nature)
        snapshot=dict(company='本机测试客户 A',document={'order_nature':nature},draft_items=rows,quote_management=state,analysis_customer={'customer_code':'LOCAL-A'})
        created=self.quote_api('',dict(snapshot=snapshot));opened=self.quote_api('/'+created['scheme_no'])
        schemes._apply_opened_scheme(self.w,opened,route=2);self.w._quote_scheme_save_timer.stop();self.w._history_price_timer.stop();base.APP.processEvents()
        return created

    def wait_contract(self):
        base.wait(lambda:not self.c.active and not self.p.busy and not self.p.queue and not self.p.workers and not self.w._quote_scheme_workers)

    def test_01_first_quote_direct_button_generates_without_adjustment_or_export(self):
        self.configure_template('docx');created=self.open_draft();self.assertEqual(self.w._quote_scheme_status,'DRAFT')
        self.assertEqual(len(self.m.state['versions']),1);self.assertTrue(self.m.detail_contract_button.isEnabled(),self.m.detail_contract_button.toolTip())
        layout=self.m.detail_contract_button.parentWidget().layout()
        # Exact approved order in the real header, independent of list selection.
        row=layout.itemAt(1).layout();texts=[row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget() and hasattr(row.itemAt(i).widget(),'text')]
        self.assertLess(texts.index('打印'),texts.index('生成合同'));self.assertLess(texts.index('导出报价单'),texts.index('生成合同'));self.assertLess(texts.index('生成合同'),texts.index('调整报价'))
        artifacts=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',str(self.folder)));artifacts.mkdir(parents=True,exist_ok=True)
        self.w.grab().save(str(artifacts/'报价单详情_首次报价直接生成合同.png'))
        with patch.object(self.m,'adjust',side_effect=AssertionError('No second adjustment')),patch.object(contracts.QFileDialog,'getSaveFileName',side_effect=AssertionError('No quotation export required')):
            self.m.detail_contract_button.click();self.wait_contract()
        self.assertEqual(self.w.stack.currentIndex(),self.m.contract_route,self.m.feedback.text())
        self.assertEqual(self.p.source.currentData(),(created['scheme_no'],1));self.assertEqual(self.p.current_quote['total'],400)
        self.assertEqual(self.w._quote_scheme_status,'QUOTED');self.assertEqual(len(self.m.state['versions']),1)
        self.assertFalse(self.w._detail_contract_busy);self.assertFalse(self.w._scheme2_document_busy)
        self.p.template.setCurrentIndex(1);self.settled();self.p.generate();self.settled()
        self.assertIsNotNone(self.p.output,self.p.notice.text());self.assertTrue(self.p.preview_pages,self.p.notice.text())
        record=self.p.record;self.assertEqual(record['generation_snapshot']['source_quote_version'],1);self.assertEqual(record['generation_snapshot']['quote']['total'],400)
        self.assertEqual(self.w._quote_scheme_status,'CONTRACT')
        self.assertEqual(record['scheme']['status'],'CONTRACT')
        target=self.folder/'direct-first-contract.docx'
        with patch.object(contracts.QFileDialog,'getSaveFileName',return_value=(str(target),'')):self.p.export_file()
        self.assertEqual(sha256(target.read_bytes()).hexdigest(),record['file_sha256'])
        # The contract remains attached to V1 and reopens as the same bytes.
        original=self.p.output['bytes'];self.p.reload();self.settled();self.p.records.selectRow(next(i for i,r in enumerate(self.p.visible_records) if r['record_id']==record['record_id']));self.p.open_record();self.settled();self.assertEqual(self.p.output['bytes'],original)

    def test_02_current_display_v3_maps_to_source_v1_and_old_v1_is_never_substituted(self):
        self.open_draft(number=3);self.m.detail_contract_button.click();self.wait_contract()
        self.assertEqual(self.p.source.currentData()[1],1);self.assertIn('正式 V3',self.p.source.currentText());self.assertIn('正式 V3',self.p.source_info.text())
        self.assertEqual(self.p.current_quote['total'],400)

    def test_03_internal_unclassified_foreign_and_void_are_blocked(self):
        for nature in ('INTERNAL','UNCLASSIFIED'):
            self.open_draft(nature);self.assertFalse(self.m.detail_contract_button.isEnabled());before=self.w._quote_scheme_id
            self.c.start();self.assertFalse(self.c.active);self.assertEqual(self.quote_api('/'+before)['status'],'DRAFT')
        self.open_draft();self.w._name_scope_foreign=True;self.m.status_changed();self.assertFalse(self.m.detail_contract_button.isEnabled());self.c.start();self.assertFalse(self.c.active)
        self.w._name_scope_foreign=False;self.w._quote_scheme_status='VOID';self.m.status_changed();self.assertFalse(self.m.detail_contract_button.isEnabled())

    def test_04_bootstrap_failure_restores_controls_and_keeps_quote(self):
        self.open_draft();before=deepcopy(self.w.draft_items)
        def fail(worker):worker.error='本机合成网络失败';worker.completed=True
        with patch.object(contracts.ContractWorker,'run',fail):self.m.detail_contract_button.click();self.wait_contract()
        self.assertEqual(self.w.draft_items,before);self.assertFalse(self.w._detail_contract_busy);self.assertFalse(self.w._scheme2_document_busy);self.assertFalse(self.w._quote_scheme_read_only)
        self.assertIn('本机合成网络失败',self.m.feedback.text())
        self.m.status_changed()  # An unrelated automatic-save status must not hide the failure.
        self.assertIn('本机合成网络失败',self.m.feedback.text())

    def test_05_history_uses_viewed_formal_version_and_missing_v2_never_falls_back(self):
        first=self.open_draft();self.m.detail_contract_button.click();self.wait_contract()
        self.quote_api('/'+first['scheme_no']+'/revision',dict(expected_version=self.w._quote_scheme_version))
        schemes._apply_opened_scheme(self.w,self.quote_api('/'+first['scheme_no']),route=2)
        self.w._quote_scheme_save_timer.stop();self.m.state['versions'].pop()
        for number,price in ((2,250),(3,300)):
            entry=model.append_version(self.m.state,[product(price)],'本机测试客户 A','合成调整',self.m.operator(),'2026-10-29','EXTERNAL');entry['confirmed']=True
        self.w.draft_items=[product(300)];self.w.refresh_summary();self.m.refresh()
        self.m.detail_contract_button.click();self.wait_contract();self.assertEqual(self.p.current_quote['total'],600,(self.m.feedback.text(),self.p.notice.text()))
        self.assertEqual(self.p.source.currentData(),(first['scheme_no'],2));self.assertIn('正式 V3',self.p.source.currentText())
        self.w.stack.setCurrentIndex(2);self.m.root.setCurrentWidget(self.m.detail_page);self.m.view_version(1)
        self.m.detail_contract_button.click();self.wait_contract();self.assertEqual(self.p.source.currentData(),(first['scheme_no'],1));self.assertEqual(self.p.current_quote['total'],400)
        self.w.stack.setCurrentIndex(2);self.m.root.setCurrentWidget(self.m.detail_page);self.m.view_version(2)
        self.m.detail_contract_button.click();self.wait_contract()
        self.assertEqual(self.w.stack.currentIndex(),2);self.assertEqual(self.m.history_version,2);self.assertIn('未找到当前 V2',self.m.feedback.text())

    def test_06_no_scheme_number_is_created_and_confirmed_in_one_action(self):
        self.open_draft();self.w._quote_scheme_id='';self.w._quote_scheme_version=0;self.w._quote_scheme_status=''
        self.m.refresh();self.m.detail_contract_button.click();self.wait_contract()
        self.assertTrue(self.w._quote_scheme_id);self.assertEqual(self.w._quote_scheme_status,'QUOTED');self.assertEqual(self.p.current_quote['total'],400)

    def test_07_cost_generate_then_contract_without_a_second_quote_edit(self):
        import scheme2_ui as ui
        self.open_draft();self.w.show_section(ui.COST_ROUTE)
        worker_class=base.NS['ApiWorker'];original=worker_class.start
        def preview(worker):
            if worker.url.endswith('/preview-check'):
                QTimer.singleShot(0,lambda:(worker.succeeded.emit(dict(valid=True,persisted=False,checked_items=1)),worker.finished.emit()))
            else:original(worker)
        controller=self.w._scheme2_document_controller
        with patch.object(worker_class,'start',preview):
            self.w.scheme2_cost_generate.click();base.wait(lambda:not controller.busy)
        self.assertEqual(self.w.stack.currentIndex(),ui.QUOTE_ROUTE)
        self.assertTrue(self.m.detail_contract_button.isEnabled(),self.m.detail_contract_button.toolTip())
        self.m.detail_contract_button.click();self.wait_contract()
        self.assertEqual(self.p.current_quote['total'],400);self.assertEqual(len(self.m.state['versions']),1)

    def test_08_lost_confirmation_reply_retries_same_snapshot_after_number_creation(self):
        import urllib.error
        self.open_draft();self.w._quote_scheme_id='';self.w._quote_scheme_version=0;self.w._quote_scheme_status=''
        self.m.refresh();original=urllib.request.urlopen
        def lose_reply(request,*args,**kwargs):
            response=original(request,*args,**kwargs)
            if request.full_url.endswith('/confirm-for-contract'):
                response.read();response.close();raise urllib.error.URLError('合成丢失回执')
            return response
        with patch('urllib.request.urlopen',side_effect=lose_reply):
            self.m.detail_contract_button.click();self.wait_contract()
        self.assertFalse(self.w._detail_contract_busy);number=self.w._quote_scheme_id
        self.m.status_changed()
        self.assertIn('合成丢失回执',self.m.feedback.text())
        with patch.object(self.c,'confirmed_quote',wraps=self.c.confirmed_quote) as confirmed:
            self.m.detail_contract_button.click();self.wait_contract()
            self.assertTrue(confirmed.call_args.args[0]['reused'])
        self.assertEqual(self.p.source.currentData(),(number,1));self.assertEqual(self.p.current_quote['total'],400)

if __name__=='__main__':unittest.main(verbosity=2)
