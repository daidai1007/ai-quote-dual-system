"""Real named HTTP + disposable DB + Qt + Office rendering; synthetic data only."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json,os,unittest,urllib.error
from unittest.mock import patch
from zipfile import ZipFile
import verify_contract_management as base
from contract_ledger_test_data import write_ledger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from PySide6.QtPrintSupport import QPrinter
import contract_management as ui
import contract_ledger_ui as ledger_ui

class LedgerUITests(unittest.TestCase):
    host_arguments=['--ledger']
    setUpClass=classmethod(base.ContractTests.setUpClass.__func__)
    tearDownClass=classmethod(base.ContractTests.tearDownClass.__func__)
    api=base.ContractTests.api
    settled=base.ContractTests.settled
    close_window=base.ContractTests.close_window

    def setUp(self):
        base.ContractTests.setUp(self)
        self.p.source_mode.setCurrentIndex(1);self.settled();self.l=self.p.ledger
        self.assertTrue(self.l.info['ready'],self.p.notice.text())

    def screenshot(self,name):
        folder=Path(os.environ.get('AI_QUOTE_CONTRACT_SCREENSHOT_DIR',str(base.ROOT/'test-output/ledger-contracts-qa')));folder.mkdir(parents=True,exist_ok=True)
        from PySide6.QtTest import QTest
        QTest.qWait(100);base.APP.processEvents()
        if self.l.preview_pages and self.l.stack.currentIndex()==2:
            geometry=[];bottom=-1
            for index in range(self.l.pagebox.count()):
                widget=self.l.pagebox.itemAt(index).widget()
                if widget is None:continue
                rect=widget.geometry()
                self.assertGreaterEqual(rect.top(),bottom+1,'Preview captions/pages overlap after layout settles')
                geometry.append(dict(y=rect.y(),height=rect.height(),width=rect.width(),picture=hasattr(widget,'source_pixmap')))
                bottom=rect.bottom()
            (folder/(name+'.geometry.json')).write_text(json.dumps(geometry),encoding='utf-8')
        self.w.grab().save(str(folder/name))

    def upload_and_read(self,customer,format):
        self.l.customer.setCurrentIndex(self.l.customer.findData(customer))
        with patch.object(ui.QFileDialog,'getOpenFileName',return_value=(str(self.folder/('synthetic-ledger-template.'+format)),'')):
            self.l.upload()
        self.settled();self.assertGreater(self.l.template.currentIndex(),0,self.p.notice.text())
        path=write_ledger(self.folder/(customer+'.xls'),customer);self.original=(path,sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns)
        self.l.read_file(path);self.settled();self.assertEqual(self.l.selection.rowCount(),2 if customer=='NUOYUE' else 3,self.p.notice.text())

    def test_01_nuoyue_groups_draft_remarks_actual_file_reopen_print_export(self):
        self.upload_and_read('NUOYUE','xlsx');self.screenshot('01_实际程序_诺玥选择台账.png')
        self.l.select_all();self.l.go(1);self.assertEqual(self.l.documents.rowCount(),2)
        self.assertEqual(self.l.items.rowCount(),3);self.assertFalse(self.l.items.item(0,1).flags() & Qt.ItemFlag.ItemIsEditable)
        self.l.items.item(0,7).setText('人工确认备注\n保留第二行');self.l.items.item(1,7).setText('')
        self.l.items.selectRow(2);self.l.items.item(2,7).setText('待恢复');self.l.restore_remark();self.assertIn('原备注 3',self.l.items.item(2,7).text())
        self.l.save_draft();self.settled();draft=deepcopy(self.l.draft);self.assertFalse(self.l.unsaved,self.p.notice.text())
        self.screenshot('02_实际程序_诺玥核对与备注编辑.png')
        path,digest,modified=self.original;self.assertEqual(sha256(path.read_bytes()).hexdigest(),digest);self.assertEqual(path.stat().st_mtime_ns,modified)
        path.unlink();self.l.new_contract();self.l.open_draft(self.l.drafts.findData(draft['draft_id']));self.settled()
        self.assertEqual(self.l.items.item(0,7).text(),'人工确认备注\n保留第二行');self.assertEqual(self.l.items.item(1,7).text(),'')
        self.l.generate();self.settled();self.assertEqual(len(self.l.generated_records),2,self.p.notice.text())
        self.assertIsNotNone(self.l.output,self.p.notice.text());self.assertTrue(self.l.preview_pages,self.p.notice.text())
        first=deepcopy(self.l.record);file=self.l.output['bytes'];self.assertEqual(sha256(file).hexdigest(),first['file_sha256'])
        self.assertEqual(first['generation_snapshot']['quote']['total'],650.3)
        self.assertEqual(first['generation_snapshot']['original_records'][0]['remark'],' 原备注 1\n第二行 ')
        with ZipFile(self.l.output['path']) as package:
            text=package.read('xl/worksheets/sheet1.xml').decode();self.assertIn('人工确认备注',text);self.assertNotIn('原备注 2',text);self.assertIn('500元',text)
        self.screenshot('03_实际程序_诺玥实际文件预览.png')
        target=self.folder/'export.xlsx'
        with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(target),'')):self.l.export_file()
        self.assertEqual(target.read_bytes(),file)
        pdf=self.folder/'printed.pdf'
        def dialog(printer,parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            value=unittest.mock.Mock();value.exec.return_value=QDialog.DialogCode.Accepted;return value
        with patch.object(ui,'QPrintDialog',side_effect=dialog):self.l.print_file()
        self.assertGreater(pdf.stat().st_size,1000)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(pdf).pages),len(self.l.preview_pages))
        self.l.choose_output(1);self.settled();self.assertEqual(self.l.record['generation_snapshot']['quote']['total'],99.99)
        self.assertNotEqual(self.l.output['bytes'],file)
        # Common generation history opens the immutable original without a ledger.
        self.p.source_mode.setCurrentIndex(0);self.p.reload();self.settled()
        row=next(i for i,r in enumerate(self.p.visible_records) if r['record_id']==first['record_id']);self.p.records.selectRow(row)
        self.p.open_record();self.settled();self.assertTrue(self.l.historical);self.assertEqual(self.l.output['bytes'],file);self.assertFalse(self.l.generate_button.isEnabled())
        self.assertEqual(self.p.tabs.count(),4)
        import name_login
        name_login.set_session(self.config['other_session']);self.w._quote_scheme_headers_factory=lambda:{'X-AI-Quote-Key':'local-contract-other','Authorization':'Bearer '+self.config['other_session']['token']}
        self.p.check_identity();self.assertIsNone(self.l.output);self.assertIsNone(self.l.imported);self.assertFalse(self.l.unsaved)

    def test_02_fangyuan_merge_new_number_word_and_permissions(self):
        self.upload_and_read('FANGYUAN','docx')
        for i in (0,2):self.l.selection.item(i,0).setCheckState(Qt.CheckState.Checked)
        self.l.go(1);self.assertEqual(self.l.documents.rowCount(),1);self.assertEqual(self.l.documents.item(0,0).text(),'')
        self.assertEqual(self.l.documents.item(0,1).text(),ui.contract_today())
        self.l.generate();self.settled();self.assertIsNone(self.l.record);self.assertIn('编号',self.p.notice.text())
        self.l.documents.item(0,0).setText('SYNTHETIC-FY-MERGED');self.l.items.item(0,7).setText('方圆人工备注')
        self.l.save_draft();self.settled();self.assertIsNotNone(self.l.draft,self.p.notice.text())
        draft=deepcopy(self.l.draft);self.l.new_contract()
        with patch.object(ledger_ui,'read_ledger',side_effect=AssertionError('Reopening must use the saved snapshot')):
            self.l.open_draft(self.l.drafts.findData(draft['draft_id']));self.settled()
        self.assertEqual(self.l.documents.item(0,0).text(),'SYNTHETIC-FY-MERGED');self.assertEqual(self.l.items.item(0,7).text(),'方圆人工备注')
        self.l.generate();self.settled();self.assertEqual(len(self.l.generated_records),1,self.p.notice.text())
        snapshot=self.l.record['generation_snapshot'];self.assertEqual(len(snapshot['quote']['items']),2);self.assertEqual(snapshot['quote']['total'],449.99)
        self.assertEqual(snapshot['fields']['contract_no'],'SYNTHETIC-FY-MERGED');self.assertTrue(self.l.preview_pages,self.p.notice.text())
        with ZipFile(self.l.output['path']) as package:self.assertIn('方圆人工备注',package.read('word/document.xml').decode())
        target=self.folder/'export.docx'
        with patch.object(ui.QFileDialog,'getSaveFileName',return_value=(str(target),'')):self.l.export_file()
        self.assertEqual(sha256(target.read_bytes()).hexdigest(),self.l.record['file_sha256']);self.screenshot('04_实际程序_方圆合并合同预览.png')
        pdf=self.folder/'printed-word.pdf'
        def word_print(printer,parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            value=unittest.mock.Mock();value.exec.return_value=QDialog.DialogCode.Accepted;return value
        with patch.object(ui,'QPrintDialog',side_effect=word_print):self.l.print_file()
        self.assertGreater(pdf.stat().st_size,1000)
        # A shared-client key cannot access the named-user ledger routes.
        with self.assertRaises(urllib.error.HTTPError) as denied:self.api('/ledger/bootstrap',key='local-shared-test')
        self.assertEqual(denied.exception.code,401)
        # Existing quotation route still forbids internal quotation contracts.
        # An injected quote identity cannot turn ledger input into an internal quote.
        invalid=self.l.input_data();invalid['order_nature']='INTERNAL'
        with self.assertRaises(urllib.error.HTTPError):self.api('/ledger/drafts',invalid)
        path,digest,modified=self.original;self.assertEqual(sha256(path.read_bytes()).hexdigest(),digest);self.assertEqual(path.stat().st_mtime_ns,modified)

if __name__=='__main__':unittest.main(verbosity=2)
