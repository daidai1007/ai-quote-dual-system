"""Actual Qt + HTTP + isolated PostgreSQL + PDF/Excel, synthetic quotes only."""
from copy import deepcopy
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
import unittest
import urllib.request
from uuid import uuid4
from unittest.mock import Mock, patch

import verify_contract_management as fixture
from verify_quote_export_customer import workbook_cell
from PySide6.QtCore import QRect
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QDialog
from pypdf import PdfReader
import name_login
import quote_scheme_center as schemes
import quote_delivery as delivery_ui

ROOT, APP, NS, wait = fixture.ROOT, fixture.APP, fixture.NS, fixture.wait


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.temporary = tempfile.TemporaryDirectory(prefix='delivery-qt-')
        cls.folder = Path(cls.temporary.name); state = cls.folder/'host.json'
        cls.log = open(cls.folder/'host.log','w',encoding='utf-8')
        cls.host = subprocess.Popen([shutil.which('node'),str(ROOT/'tests/helpers/contract_test_host.mjs'),str(state),'--quote-delivery'],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=cls.log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        until=time.monotonic()+110
        while time.monotonic()<until and not state.is_file() and cls.host.poll() is None: time.sleep(.1)
        if not state.is_file(): raise AssertionError('Local API startup failed: '+(cls.folder/'host.log').read_text(encoding='utf-8')[-1500:])
        cls.config=json.loads(state.read_text(encoding='utf-8')); cls.real_urlopen=urllib.request.urlopen
        cls.owner=cls.login('本机人员甲'); cls.recipient=cls.login('本机接收乙'); cls.other=cls.login('未接收丙')
        def local_only(request,*args,**kwargs):
            url=request.full_url if hasattr(request,'full_url') else str(request)
            if not url.startswith(cls.config['base']+'/'): raise AssertionError('External network forbidden')
            return cls.real_urlopen(request,*args,**kwargs)
        cls.network=patch('urllib.request.urlopen',side_effect=local_only);cls.network.start()

    @classmethod
    def login(cls,name):
        request=urllib.request.Request(cls.config['base']+'/api/name-login',data=json.dumps({'name':name},ensure_ascii=False).encode('utf-8'),headers={'X-AI-Quote-Key':cls.config['key'],'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()
        if cls.host.poll() is None: cls.host.communicate(b'done\n',timeout=45)
        cls.log.close();cls.temporary.cleanup()

    def api(self,path,payload=None,session=None):
        session=session or self.owner
        request=urllib.request.Request(self.config['base']+path,data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            headers={'X-AI-Quote-Key':self.config['key'],'Content-Type':'application/json','Authorization':'Bearer '+session['token']})
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)

    def setUp(self):
        self.windows=[]
        screen=Mock(wraps=APP.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.screen=patch.object(NS['MainWindow'],'screen',return_value=screen);self.screen.start();self.addCleanup(self.screen.stop)
        self.addCleanup(self.close_windows)

    def new_window(self,session):
        name_login.set_session(session)
        w=NS['MainWindow']();self.windows.append(w)
        w.base_url=lambda:self.config['base'];w._quote_scheme_headers_factory=lambda:{'X-AI-Quote-Key':self.config['key'],'Authorization':'Bearer '+session['token']}
        w._quote_scheme_save_timer.stop();w._history_price_timer.stop();w.resize(1440,960);w.show()
        return w

    def settled(self,w):
        wait(lambda:not w._quote_scheme_workers,timeout=45)
        w._quote_scheme_save_timer.stop();APP.processEvents()

    def close_windows(self):
        for w in self.windows:
            w.quote_management.delivery.leave_cost(refresh=False)
            wait(lambda:not w._quote_scheme_workers,timeout=45)
            w._quote_scheme_save_timer.stop();w._history_price_timer.stop();w._scheme2_dirty=False
            w._quote_delivery_output_pending=None;w.quote_management.delivery.pending_send=None
            if w.quote_management.delivery.send_dialog:w.quote_management.delivery.send_dialog.hide()
            w.contract_management.shutdown();w.hide();w.deleteLater();APP.processEvents()
        name_login.set_session(self.owner)

    def send_api(self,kind='EXTERNAL'):
        if kind=='EXTERNAL':no=self.config['scheme_no']
        else:
            snap=deepcopy(self.api('/api/quote-schemes/'+self.config['scheme_no'])['snapshot']);snap['document']['order_nature']=kind
            made=self.api('/api/quote-schemes',{'snapshot':snap});no=made['scheme_no']
            self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=1,kind='XLSX',succeeded=True,snapshot=snap))
        self.api('/api/quote-deliveries',dict(request_id=str(uuid4()),scheme_no=no,source_version_no=1,quote_version=1,recipient_names=['本机接收乙'],note='指定版本，示例附言 <A>'))
        row=self.api('/api/quote-deliveries?mode=sent&scheme_no='+no)['items'][0]
        return row

    def open_recipient(self,row):
        w=self.new_window(self.recipient);d=w.quote_management.delivery
        d.show_inbox();self.settled(w);d.open_received(row['delivery_id']);self.settled(w)
        self.assertEqual(w.quote_management.root.currentWidget(),d.received_page)
        return w,d

    def pdf_printer(self,name):
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        path=self.folder/name;printer.setOutputFileName(str(path));return printer,path

    def test_01_actual_send_dialog_inbox_pdf_excel_and_workspace_isolation(self):
        owner=self.new_window(self.owner);m=owner.quote_management
        schemes._open_scheme(owner,self.config['scheme_no'],route=2);self.settled(owner)
        m.delivery.start_send();self.settled(owner);dialog=m.delivery.send_dialog
        self.assertIsNotNone(dialog);self.assertTrue(dialog.isVisible());self.assertIn('本机接收乙',dialog.choices)
        out=ROOT/'.codex-tmp/quote-delivery-qa';out.mkdir(parents=True,exist_ok=True)
        self.assertEqual(m.amount.text(),'¥ 650.30')
        owner.grab().save(str(out/'quote-detail.png'));dialog.grab().save(str(out/'send-dialog.png'))
        dialog.confirm.click();self.assertIn('至少选择',dialog.error.text())
        dialog.choices['本机接收乙'].setChecked(True);dialog.note.setPlainText('请核对 V1');dialog.confirm.click();self.settled(owner)
        self.assertIsNone(m.delivery.pending_send);self.assertIn('已发送',m.delivery.sent_notice.text())
        records=self.api('/api/quote-deliveries?mode=sent&scheme_no='+self.config['scheme_no'])['items']
        row=next(r for r in records if r['note']=='请核对 V1')
        before=self.api('/api/quote-schemes/'+self.config['scheme_no'])
        w,d=self.open_recipient(row);workspace=deepcopy(w.draft_items);current=w._quote_scheme_id
        self.assertEqual(d.received['document']['total'],650.3);self.assertIn('V1',d.received_title.text());self.assertIn('请核对 V1',d.received_meta.text())
        self.assertTrue(d.print_button.isEnabled());self.assertTrue(d.export_button.isEnabled())
        printer,pdf=self.pdf_printer('received-external.pdf');dialog=Mock();dialog.exec.return_value=QDialog.DialogCode.Accepted
        with patch.object(delivery_ui,'QPrinter',Mock(return_value=printer,PrinterMode=QPrinter.PrinterMode,PrinterState=QPrinter.PrinterState)),patch.object(delivery_ui,'QPrintDialog',return_value=dialog):
            d.print_received();self.settled(w)
        text=''.join(page.extract_text() for page in PdfReader(str(pdf)).pages)
        for value in ['650.30','175.00','V1','外部',self.config['scheme_no']]:self.assertIn(value,text)
        xlsx=self.folder/'received-external.xlsx'
        with patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=(str(xlsx),'')):
            d.export_received();self.settled(w)
        for cell,value in [('E2','V1'),('B3','外部'),('F10','175'),('G10','350'),('G12','650.3')]:self.assertEqual(workbook_cell(xlsx,'报价单',cell),value,cell)
        self.assertEqual(w.draft_items,workspace);self.assertEqual(w._quote_scheme_id,current)
        self.assertEqual(self.api('/api/quote-schemes/'+self.config['scheme_no']),before)
        self.assertIsNone(w._quote_delivery_output_pending)
        out=ROOT/'.codex-tmp/quote-delivery-qa';out.mkdir(parents=True,exist_ok=True)
        w.grab().save(str(out/'received-quote.png'))

    def test_02_lost_send_response_retries_same_request_without_duplicate(self):
        w=self.new_window(self.owner);d=w.quote_management.delivery
        schemes._open_scheme(w,self.config['scheme_no'],route=2);self.settled(w);d.start_send();self.settled(w)
        dialog=d.send_dialog;dialog.choices['本机接收乙'].setChecked(True);dialog.note.setPlainText('丢包重试示例')
        real=d.request;lost=[True];ids=[]
        def request(method,suffix,payload,success,failure=None):
            if method=='POST' and suffix=='':
                ids.append(payload['request_id'])
                def response(value):
                    if lost[0]:lost[0]=False;failure('模拟响应丢失')
                    else:success(value)
                return real(method,suffix,payload,response,failure)
            return real(method,suffix,payload,success,failure)
        with patch.object(d,'request',side_effect=request):
            dialog.confirm.click();self.settled(w);self.assertIsNotNone(d.pending_send);self.assertFalse(dialog.note.isEnabled())
            self.assertTrue(name_login.critical_tasks(w));dialog.confirm.click();self.settled(w)
        self.assertEqual(len(ids),2);self.assertEqual(ids[0],ids[1]);self.assertIsNone(d.pending_send)
        records=self.api('/api/quote-deliveries?mode=sent&scheme_no='+self.config['scheme_no'])['items']
        self.assertEqual(sum(r['note']=='丢包重试示例' for r in records),1)

    def test_03_print_cancel_and_failed_registration_retry_do_not_print_twice(self):
        row=self.send_api();w,d=self.open_recipient(row)
        with patch.object(delivery_ui,'QPrintDialog') as factory:
            factory.return_value.exec.return_value=QDialog.DialogCode.Rejected;d.print_received()
        self.assertIsNone(w._quote_delivery_output_pending)
        printer,pdf=self.pdf_printer('retry-once.pdf');real=d.request;calls=[]
        def reject_output(method,suffix,payload,success,failure=None):
            if suffix.endswith('/outputs'):calls.append(deepcopy(payload));failure('模拟登记失败');return
            return real(method,suffix,payload,success,failure)
        with patch.object(d,'request',side_effect=reject_output),patch.object(delivery_ui,'QPrinter',Mock(return_value=printer,PrinterMode=QPrinter.PrinterMode,PrinterState=QPrinter.PrinterState)),patch.object(delivery_ui,'QPrintDialog') as factory:
            factory.return_value.exec.return_value=QDialog.DialogCode.Accepted;d.print_received()
            self.assertEqual(factory.call_count,1)
        digest=pdf.read_bytes();pending=deepcopy(w._quote_delivery_output_pending)
        self.assertTrue(name_login.critical_tasks(w));self.assertTrue(d.retry_output.isVisible());self.assertFalse(d.print_button.isEnabled())
        d.retry_output.click();self.settled(w)
        self.assertIsNone(w._quote_delivery_output_pending);self.assertEqual(pdf.read_bytes(),digest);self.assertEqual(pending['output_id'],calls[0]['output_id'])

    def test_04_internal_received_output_keeps_contract_and_original_permissions(self):
        row=self.send_api('INTERNAL');w,d=self.open_recipient(row)
        self.assertEqual(d.received['document']['order_nature'],'INTERNAL')
        self.assertIn('内部',d.received_preview.toPlainText())
        original_fields=set(d.received['document']['items'][0])
        self.assertNotIn('formula',original_fields);self.assertNotIn('attachments',original_fields)
        no=d.received['document']['scheme_no']
        bootstrap=self.api('/api/contracts/bootstrap',session=self.recipient)
        self.assertFalse(any(s['scheme_no']==no for s in bootstrap['sources']))
        xlsx=self.folder/'received-internal.xlsx'
        with patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=(str(xlsx),'')):
            d.export_received();self.settled(w)
        self.assertEqual(workbook_cell(xlsx,'报价单','B3'),'内部');self.assertEqual(workbook_cell(xlsx,'报价单','G12'),'650.3')
        printer,pdf=self.pdf_printer('received-internal.pdf')
        with patch.object(delivery_ui,'QPrinter',Mock(return_value=printer,PrinterMode=QPrinter.PrinterMode,PrinterState=QPrinter.PrinterState)),patch.object(delivery_ui,'QPrintDialog') as factory:
            factory.return_value.exec.return_value=QDialog.DialogCode.Accepted;d.print_received();self.settled(w)
        text=''.join(page.extract_text() for page in PdfReader(str(pdf)).pages);self.assertIn('内部',text);self.assertIn('650.30',text)

    def test_05_export_cancel_and_write_failure_do_not_register_output(self):
        row=self.send_api();w,d=self.open_recipient(row)
        with patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=('', '')),patch.object(d,'request') as request:
            d.export_received();request.assert_not_called()
        with patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=(str(self.folder/'unwritable.xlsx'),'')),patch.object(delivery_ui,'QSaveFile') as file,patch.object(d,'completed_output') as completed:
            file.return_value.open.return_value=False;d.export_received();self.settled(w);completed.assert_not_called()
        self.assertIn('无法写入',d.output_status.text());self.assertIsNone(w._quote_delivery_output_pending)

    def test_06_reopened_received_v1_stays_fixed_after_source_formal_v2(self):
        row=self.send_api('INTERNAL');no=row['scheme_no']
        source=self.api('/api/quote-schemes/'+no)
        revised=self.api('/api/quote-schemes/'+no+'/revision',dict(expected_version=source['lock_version']))
        snapshot=deepcopy(source['snapshot']);snapshot['quote_management']={'schema':1,'current':2,'versions':[]}
        snapshot['draft_items'][0]['quote_display'].update(unit_price=999,total=1998)
        snapshot['scheme_summary']['quoted_amount']=2298.3
        self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=revised['lock_version'],kind='XLSX',succeeded=True,snapshot=snapshot))
        w,d=self.open_recipient(row);self.assertEqual(d.received['document']['quote_version'],1);self.assertEqual(d.received['document']['total'],650.3)
        self.assertEqual(self.api('/api/quote-schemes/'+no)['quoted_amount'],2298.3)
        xlsx=self.folder/'historical-sent-v1.xlsx'
        with patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=(str(xlsx),'')):
            d.export_received();self.settled(w)
        self.assertEqual(workbook_cell(xlsx,'报价单','E2'),'V1');self.assertEqual(workbook_cell(xlsx,'报价单','G12'),'650.3')
        frozen=deepcopy(d.received['document']);d.show_inbox();self.settled(w);d.open_received(row['delivery_id']);self.settled(w)
        self.assertEqual(d.received['document'],frozen)

    def test_07_corrupt_download_preserves_existing_file_and_has_no_output_record(self):
        row=self.send_api();w,d=self.open_recipient(row);target=self.folder/'preserved.xlsx';target.write_bytes(b'previous-synthetic-file')
        real=type(self).real_urlopen
        def corrupt(request,*args,**kwargs):
            response=real(request,*args,**kwargs)
            if request.full_url.endswith('/xlsx'):response.headers.replace_header('X-Content-SHA256','0'*64)
            return response
        with patch('urllib.request.urlopen',side_effect=corrupt),patch.object(delivery_ui.QFileDialog,'getSaveFileName',return_value=(str(target),'')),patch.object(d,'completed_output') as completed:
            d.export_received();self.settled(w);completed.assert_not_called()
        self.assertEqual(target.read_bytes(),b'previous-synthetic-file');self.assertIn('完整性校验失败',d.output_status.text())

    def test_08_inbox_two_actions_open_real_cost_route_without_changing_workspace(self):
        import scheme2_ui as ui
        row=self.send_api('INTERNAL');w=self.new_window(self.recipient);d=w.quote_management.delivery
        workspace=deepcopy(w.draft_items);scheme_id=w._quote_scheme_id;readonly=w._quote_scheme_read_only
        d.show_inbox();self.settled(w)
        found=False
        for index in range(d.inbox_table.rowCount()):
            if row['scheme_no'] in d.inbox_table.item(index,0).text():
                host=d.inbox_table.cellWidget(index,6);buttons=host.findChildren(delivery_ui.QPushButton)
                self.assertEqual([b.text() for b in buttons],['打开报价','进入成本计算'])
                buttons[1].click();found=True;break
        self.assertTrue(found);self.settled(w)
        self.assertEqual(w.stack.currentIndex(),ui.COST_ROUTE);self.assertTrue(d.cost_active)
        self.assertTrue(d.cost_banner.isVisible());self.assertIn('V1',d.cost_meta.text());self.assertIn('内部',d.cost_meta.text())
        self.assertEqual(w.summary_table.item(0,13).text(),'175.00')
        self.assertEqual(w.summary_table.item(0,12).text(),'未记录')
        self.assertFalse(w.scheme2_cost_generate.isEnabled());self.assertFalse(w.scheme2_cost_edit_coefficients.isEnabled())
        self.assertEqual(w.summary_table.editTriggers(),delivery_ui.QAbstractItemView.EditTrigger.NoEditTriggers)
        with patch.object(ui,'_row_values',side_effect=AssertionError('No repricing of a received version')),patch.object(ui,'_recalculate_item_management',side_effect=AssertionError('No new cost rules')):
            ui._refresh_cost_table(w)
        ui._delete_selected(w);ui._duplicate_selected(w);ui._undo_delete(w)
        self.assertEqual(w.draft_items,workspace);self.assertEqual(w._quote_scheme_id,scheme_id)
        out=ROOT/'.codex-tmp/quote-delivery-qa';out.mkdir(parents=True,exist_ok=True)
        w.grab().save(str(out/'received-cost-calculation.png'))
        w.resize(1024,768);APP.processEvents();d.enforce_cost_readonly()
        self.assertFalse(w.scheme2_cost_generate.isEnabled());self.assertEqual(w.stack.currentIndex(),ui.COST_ROUTE)
        w.grab().save(str(out/'received-cost-calculation-1024.png'))
        next(b for b in d.cost_banner.findChildren(delivery_ui.QPushButton) if b.text()=='返回收到的报价').click();self.settled(w)
        self.assertFalse(d.cost_active);self.assertEqual(w.stack.currentIndex(),ui.QUOTE_ROUTE)
        self.assertEqual(w.quote_management.root.currentWidget(),d.inbox_page)
        self.assertEqual(w._quote_scheme_read_only,readonly);self.assertEqual(w.draft_items,workspace)
        w.grab().save(str(out/'received-two-actions.png'))
        d.open_received(row['delivery_id']);self.settled(w)
        self.assertEqual(d.received_table.item(10,5).text(),'175.00');self.assertEqual(d.received_table.item(12,6).text(),'650.30')
        self.assertEqual(d.received_tabs.count(),5);self.assertIn('报价单详情',d.received_title.text())
        for control in (d.print_button,d.export_button,*d.received_nature.values()):
            self.assertTrue(control.parentWidget().rect().contains(control.geometry()),control.text())
        w.grab().save(str(out/'received-quote-1024.png'))

    def test_09_received_costs_stay_at_v1_after_formal_v2_and_preserve_own_draft(self):
        import scheme2_ui as ui
        row=self.send_api('INTERNAL');no=row['scheme_no'];source=self.api('/api/quote-schemes/'+no)
        revised=self.api('/api/quote-schemes/'+no+'/revision',dict(expected_version=source['lock_version']))
        snapshot=deepcopy(source['snapshot']);snapshot['quote_management']={'schema':1,'current':2,'versions':[]}
        snapshot['draft_items'][0]['formula']['material_cost']=999
        self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=revised['lock_version'],kind='XLSX',succeeded=True,snapshot=snapshot))
        w=self.new_window(self.recipient);d=w.quote_management.delivery
        own=[{'name':'本人未完成草稿','quantity':9,'quick':{'base_price':1,'total_cost':1},'formula':{'material_cost':1}}]
        w.draft_items=deepcopy(own);w._quote_scheme_save_timer.stop();d.show_inbox();self.settled(w)
        own=deepcopy(w.draft_items)  # Baseline after the existing quote/remark normalization.
        d.open_received(row['delivery_id'],'cost');self.settled(w)
        self.assertEqual(w.stack.currentIndex(),ui.COST_ROUTE);self.assertEqual(w.summary_table.item(0,13).text(),'175.00')
        self.assertEqual(w.draft_items,own);self.assertIn('V1',d.cost_meta.text())
        w.show_section(ui.OPTION_ROUTE);self.assertFalse(d.cost_active);self.assertEqual(w.draft_items,own)


if __name__=='__main__': unittest.main(verbosity=2)
