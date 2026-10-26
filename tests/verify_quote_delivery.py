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
        m.delivery.send_button.click();self.settled(owner);dialog=m.delivery.send_dialog
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


    def test_10_received_price_breakdowns_are_frozen_and_never_recalculated(self):
        import scheme2_ui as ui
        snap=deepcopy(self.api('/api/quote-schemes/'+self.config['scheme_no'])['snapshot'])
        first=snap['draft_items'][0]
        first['quote_cost_display']={'schema':1,'values':{'固定报价':'25.00','折扣面价':'150.00'},
            'price_breakdown':{'schema':1,'basis':'per_unit_set_v1',
                'fixed':{'rows':[dict(category='运费',original=25,discount=1,amount=25)],'total':25},
                'discounted':{'rows':[dict(category='柜体',original=300,discount=.5,amount=150)],'total':150},'total':175}}
        created=self.api('/api/quote-schemes',{'snapshot':snap});no=created['scheme_no']
        self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=1,kind='XLSX',succeeded=True,snapshot=snap))
        sent=self.api('/api/quote-deliveries',dict(request_id=str(uuid4()),scheme_no=no,source_version_no=1,quote_version=1,recipient_names=['本机接收乙'],note='冻结分项'))
        row=self.api('/api/quote-deliveries?mode=sent&scheme_no='+no)['items'][0]
        source=self.api('/api/quote-schemes/'+no)
        revised=self.api('/api/quote-schemes/'+no+'/revision',dict(expected_version=source['lock_version']))
        changed=deepcopy(snap);changed['quote_management']={'schema':1,'current':2,'versions':[]}
        changed['draft_items'][0]['quote_cost_display']['price_breakdown']['fixed']['total']=999
        self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=revised['lock_version'],kind='XLSX',succeeded=True,snapshot=changed))
        w=self.new_window(self.recipient);d=w.quote_management.delivery;before=deepcopy(w.draft_items)
        d.open_received(row['delivery_id'],'cost');self.settled(w)
        self.assertEqual(w.summary_table.item(0,7).text(),'25.00')
        self.assertEqual(w.summary_table.item(0,24).text(),'150.00')
        opened=[]
        def inspect(dialog):
            opened.append([dialog.table.item(dialog.table.rowCount()-1,c).text() for c in range(4)])
            return QDialog.DialogCode.Accepted
        with (patch.object(ui,'_cost_price_components',side_effect=AssertionError('Received costs must not recalculate')),
              patch.object(ui.QuickPriceBreakdownDialog,'exec',inspect)):
            for column in (7,24):
                link=w.scheme2_cost_selection_values[column]
                self.assertTrue(link.isEnabled())
                self.assertEqual(link.text(),w.summary_table.item(0,column).text())
                link.click()
            ui._cost_cell_clicked(w,1,7)
        self.assertEqual([r[3] for r in opened],['25.00','150.00','未记录'])
        self.assertEqual(w.draft_items,before)


    def test_11_received_formula_attachment_details_use_frozen_saved_categories(self):
        import scheme2_ui as ui
        from PySide6.QtWidgets import QTableWidget
        snap=deepcopy(self.api('/api/quote-schemes/'+self.config['scheme_no'])['snapshot'])
        first=snap['draft_items'][0]
        first['quote_cost_display']={'schema':1,'values':{'材料成本':'100.00','喷涂费用':'12.00','辅材成本':'8.00','人工成本':'20.00','附件成本':'30.00'}}
        first['cost_detail_rows']=[dict(type=label,name='合成附件－'+label,base_amount=value,factor=1,note='附件公式成本分项')
            for label,value in [('材料成本',80),('喷涂费用',12),('辅材成本',8),('人工成本',20)]]
        created=self.api('/api/quote-schemes',{'snapshot':snap});no=created['scheme_no']
        self.api('/api/quote-schemes/'+no+'/export-result',dict(expected_version=1,kind='XLSX',succeeded=True,snapshot=snap))
        self.api('/api/quote-deliveries',dict(request_id=str(uuid4()),scheme_no=no,source_version_no=1,quote_version=1,recipient_names=['本机接收乙'],note='公式成本拆分'))
        row=self.api('/api/quote-deliveries?mode=sent&scheme_no='+no)['items'][0]
        w=self.new_window(self.recipient);d=w.quote_management.delivery;before=deepcopy(w.draft_items)
        d.open_received(row['delivery_id'],'cost');self.settled(w)
        self.assertEqual(w.summary_table.item(0,16).text(),'30.00')
        captured=[]
        def inspect(dialog):
            grid=dialog.findChild(QTableWidget)
            captured.extend([[grid.item(r,c).text() for c in range(grid.columnCount())] for r in range(grid.rowCount())])
            return QDialog.DialogCode.Accepted
        with patch.object(delivery_ui.QDialog,'exec',inspect):d.show_cost_detail(0)
        self.assertEqual([row[2] for row in captured],['80.00','12.00','8.00','20.00'])
        self.assertEqual(w.draft_items,before)
    def sender_window(self):
        w=self.new_window(self.owner);m=w.quote_management
        schemes._open_scheme(w,self.config['scheme_no'],route=2);self.settled(w)
        self.assertEqual(w._quote_scheme_status,'QUOTED')
        self.assertTrue(m.delivery.send_button.isEnabled())
        return w,m,m.delivery

    def test_10_versions_error_remains_visible_after_save_status_refresh(self):
        w,m,d=self.sender_window()
        with patch.object(d,'request',side_effect=lambda method,suffix,payload,success,failure:failure('同事发送功能尚未开通')):
            d.send_button.click()
        m.status_changed();APP.processEvents()
        self.assertIsNone(d.send_dialog);self.assertTrue(d.send_status.isVisible())
        self.assertIn('同事发送功能尚未开通',d.send_status.text())
        self.assertTrue(d.send_button.isEnabled());self.assertEqual(d.send_button.text(),'发送给同事')
        self.assertEqual(m.detail_page.layout().indexOf(d.send_status),2)

    def test_11_quoted_without_sendable_version_explains_registration(self):
        w,m,d=self.sender_window()
        with patch.object(d,'request',side_effect=lambda method,suffix,payload,success,failure:success({'items':[]})) as request:
            d.send_button.click()
        m.status_changed();APP.processEvents()
        self.assertEqual(request.call_count,1);self.assertIsNone(d.send_dialog)
        self.assertTrue(d.send_status.isVisible());self.assertIn('V1',d.send_status.text())
        self.assertIn('请联系管理员核对正式版本数据',d.send_status.text())

    def test_12_colleagues_error_is_visible_and_retry_opens_dialog(self):
        w,m,d=self.sender_window();request=d.request
        def fail_people(method,suffix,payload,success,failure):
            if suffix=='/colleagues':return failure('姓名会话已失效，请重新登录。')
            return request(method,suffix,payload,success,failure)
        with patch.object(d,'request',side_effect=fail_people):
            d.send_button.click();self.settled(w)
        m.status_changed();self.assertTrue(d.send_status.isVisible())
        self.assertIn('会话已失效',d.send_status.text());self.assertIsNone(d.send_dialog)
        d.send_button.click();self.settled(w)
        self.assertIsNotNone(d.send_dialog);self.assertTrue(d.send_dialog.isVisible())
        self.assertTrue(d.send_status.isHidden());self.assertFalse(d.send_loading)

    def test_13_pending_send_check_survives_refresh_and_prevents_duplicate(self):
        w,m,d=self.sender_window();callbacks=[]
        with patch.object(d,'request',side_effect=lambda method,suffix,payload,success,failure:callbacks.append((success,failure))) as request:
            d.send_button.click();m.status_changed();APP.processEvents()
            self.assertTrue(d.send_loading);self.assertFalse(d.send_button.isEnabled())
            self.assertEqual(d.send_button.text(),'正在核对…');self.assertTrue(d.send_status.isVisible())
            d.send_button.click();d.start_send();self.assertEqual(request.call_count,1)
            callbacks[0][1]('本机模拟超时')
        self.assertFalse(d.send_loading);self.assertTrue(d.send_button.isEnabled())
        self.assertIn('本机模拟超时',d.send_status.text())

    def test_14_source_change_hides_old_feedback_and_ignores_old_response(self):
        w,m,d=self.sender_window();callbacks=[]
        original_no=w._quote_scheme_id
        try:
            with patch.object(d,'request',side_effect=lambda method,suffix,payload,success,failure:callbacks.append((success,failure))) as request:
                d.send_button.click();w._quote_scheme_id='BJ-20261026-999999'
                callbacks[0][0]({'items':[]});m.status_changed()
                self.assertEqual(request.call_count,1);self.assertIsNone(d.send_dialog)
                self.assertFalse(d.send_loading);self.assertTrue(d.send_status.isHidden())
        finally:w._quote_scheme_id=original_no

    def test_15_request_setup_error_is_visible_and_does_not_lock_button(self):
        w,m,d=self.sender_window()
        with patch.object(d,'request',side_effect=RuntimeError('旧姓名请求已停止，请重新操作。')):
            d.send_button.click()
        m.status_changed();self.assertTrue(d.send_status.isVisible())
        self.assertIn('旧姓名请求已停止',d.send_status.text());self.assertFalse(d.send_loading)
        self.assertTrue(d.send_button.isEnabled())

    def test_16_void_and_foreign_quotes_still_cannot_send(self):
        w,m,d=self.sender_window()
        with patch.object(d,'request') as request:
            w._name_scope_foreign=True;d.refresh();d.send_button.click();d.start_send()
            self.assertFalse(d.send_button.isEnabled());request.assert_not_called()
            w._name_scope_foreign=False;w._quote_scheme_status='VOID';d.refresh()
            d.send_button.click();d.start_send();request.assert_not_called()

    def test_17_real_http_error_is_visible_after_refresh(self):
        w,m,d=self.sender_window();request=d.request
        def invalid_endpoint(method,suffix,payload,success,failure):
            return request(method,'/invalid-version-probe',payload,success,failure)
        with patch.object(d,'request',side_effect=invalid_endpoint):
            d.send_button.click();self.settled(w)
        m.status_changed();self.assertIsNone(d.send_dialog)
        self.assertTrue(d.send_status.isVisible());self.assertIn('请求标识无效',d.send_status.text())
        self.assertFalse(d.send_loading);self.assertTrue(d.send_button.isEnabled())

    def test_18_unexpected_version_response_is_visible(self):
        w,m,d=self.sender_window()
        with patch.object(d,'request',side_effect=lambda method,suffix,payload,success,failure:success({'items':[{}]})):
            d.send_button.click()
        m.status_changed();self.assertIsNone(d.send_dialog)
        self.assertIn('正式版本数据格式异常',d.send_status.text())
        self.assertTrue(d.send_status.isVisible());self.assertFalse(d.send_loading)


    def test_19_legacy_quoted_unclassified_explains_revision_without_writes(self):
        w,m,d=self.sender_window();w._quote_order_nature='UNCLASSIFIED'
        before=deepcopy(w.draft_items)
        with patch.object(d,'request') as request:
            d.send_button.click();m.status_changed()
            request.assert_not_called()
        self.assertIsNone(d.send_dialog);self.assertTrue(d.send_status.isVisible())
        self.assertIn('待分类',d.send_status.text());self.assertIn('创建修订版',d.send_status.text())
        self.assertEqual(w._quote_order_nature,'UNCLASSIFIED');self.assertEqual(w.draft_items,before)
        self.assertFalse(d.send_loading);self.assertTrue(d.send_button.isEnabled())



if __name__=='__main__': unittest.main(verbosity=2)
