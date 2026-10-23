"""Actual Qt detail surface, synthetic save/reopen and real PDF print output."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import os

import verify_quote_export_customer as customer_fixture
from verify_quote_export_customer import app, ui
from verify_quote_document_progress import wait
from PySide6.QtPrintSupport import QPrinter
from pypdf import PdfReader
from PySide6.QtWidgets import QDialog
from PySide6.QtCore import QRect
import quote_scheme_center as schemes
import quote_order_nature as nature


class OrderNatureTests(unittest.TestCase):
    def setUp(self):
        self.h=customer_fixture.ExportCustomer();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.w=self.h.window;self.m=self.w.quote_management
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        self.w.screen=lambda:screen
        self.w._quote_order_nature='UNCLASSIFIED'
        self.m.state['versions']=[];self.m.sync();self.w.refresh_summary()
        self.w._quote_scheme_save_timer.stop()
        self.amount=ui._row_values(self.w.draft_items[0])[16]

    def save(self):
        self.m.save();wait(lambda:not self.w._quote_scheme_workers)
        self.w._quote_scheme_save_timer.stop()

    def choose(self,value):
        self.m.nature_controls[value].click();self.w._quote_scheme_save_timer.stop()

    def test_unclassified_draft_save_reopen_and_discard_are_consistent(self):
        self.assertFalse(any(control.isChecked() for control in self.m.nature_controls.values()))
        self.assertFalse(self.w.scheme2_quote_print.isEnabled())
        self.assertFalse(self.w.scheme2_quote_export.isEnabled())
        self.save();self.assertEqual(self.h.server['snapshot']['document']['order_nature'],'UNCLASSIFIED')
        self.choose('INTERNAL');self.save()
        saved=deepcopy(self.h.server['snapshot'])
        self.assertEqual(saved['document']['order_nature'],'INTERNAL')
        self.assertEqual(saved['quote_management']['versions'][-1]['order_nature'],'INTERNAL')
        self.choose('EXTERNAL');self.m.discard();wait(lambda:not self.w._quote_scheme_workers)
        self.assertEqual(nature.current(self.w),'INTERNAL')
        schemes._apply_opened_scheme(self.w,dict(self.h.server,snapshot=saved),route=ui.QUOTE_ROUTE)
        self.assertTrue(self.m.nature_controls['INTERNAL'].isChecked())
        self.assertEqual(self.w.scheme2_quote_preview.item(2,4).text(),'内部')
        self.assertEqual(ui._quote_export_items_snapshot(self.w)[0]['quote_order_nature'],'INTERNAL')
        self.assertEqual(ui._row_values(self.w.draft_items[0])[16],self.amount)

    def test_actual_pdf_print_retry_reuses_frozen_classification_without_printing_twice(self):
        self.choose('INTERNAL');self.save()
        destination=Path(self.h.folder.name)/'internal-print.pdf'
        printer=QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(destination))
        dialog=Mock();dialog.exec.return_value=QDialog.DialogCode.Accepted
        self.h.registration_error='synthetic registration disconnect'
        with patch.object(ui,'QPrinter',Mock(return_value=printer,PrinterMode=QPrinter.PrinterMode)),patch.object(ui,'QPrintDialog',return_value=dialog) as factory:
            ui._print_quote(self.w)
            wait(lambda:not self.h.controller.busy and not self.w._quote_scheme_workers)
            self.assertEqual(factory.call_count,1)
            self.assertTrue(destination.read_bytes().startswith(b'%PDF'))
            digest=sha256(destination.read_bytes()).hexdigest()
            receipt=deepcopy(self.w._quote_scheme_pending_export['payload'])
            self.assertEqual(receipt['kind'],'PRINT');self.assertEqual(receipt['snapshot']['document']['order_nature'],'INTERNAL')
            self.assertIn('无需重复打印',self.w.quote_scheme_operation_status.text())
            self.m.nature_controls['EXTERNAL'].click();self.assertEqual(nature.current(self.w),'INTERNAL')
            self.h.registration_error=None
            self.h.controller.feedback['export']['retry'].click()
            wait(lambda:not self.h.controller.busy and not self.w._quote_scheme_workers)
            self.assertEqual(factory.call_count,1)
            self.assertEqual(sha256(destination.read_bytes()).hexdigest(),digest)
        pdf=PdfReader(str(destination))
        text=''.join(page.extract_text() for page in pdf.pages)
        self.assertIn('订单性质',text);self.assertIn('内部',text)
        self.assertIn(f'{self.amount:,.2f}',text)
        self.assertIn(f'{ui._row_values(self.w.draft_items[0])[15]:,.2f}',text)
        self.assertEqual(self.w._quote_scheme_status,'QUOTED')
        self.assertEqual(self.h.posts()[-1],receipt)
        self.assertTrue(all(not control.isEnabled() for control in self.m.nature_controls.values()))
        self.assertEqual(ui._row_values(self.w.draft_items[0])[16],self.amount)

    def test_cancel_print_restores_draft_and_classification_controls(self):
        self.choose('EXTERNAL');self.save()
        dialog=Mock();dialog.exec.return_value=QDialog.DialogCode.Rejected
        with patch.object(ui,'QPrintDialog',return_value=dialog):ui._print_quote(self.w)
        self.assertIsNone(self.w._quote_scheme_export_context)
        self.assertFalse(self.w._quote_scheme_read_only)
        self.assertTrue(self.m.nature_controls['INTERNAL'].isEnabled())
        self.assertEqual(nature.current(self.w),'EXTERNAL')
        self.assertEqual(self.h.posts(),[])

    def test_local_workspace_saved_from_history_keeps_latest_classification(self):
        import quote_management_model as model
        self.choose('EXTERNAL');self.m.sync()
        first=deepcopy(self.m.state['versions'][0]);first['order_nature']='UNCLASSIFIED';first['sealed']=True
        second=model.make_version(self.w.draft_items,self.w.scheme2_company.currentText(),2,'合成修订','本机测试','2026-10-23','EXTERNAL');second['sealed']=True
        self.w._qm_state=dict(schema=1,current=2,versions=[first,second])
        self.w._quote_scheme_status='QUOTED';self.w._quote_scheme_read_only=True
        self.m.view_version(1)
        self.assertEqual(nature.current(self.w),'UNCLASSIFIED')
        payload=ui._order_workspace_payload(self.w)
        self.assertEqual(payload['order_nature'],'EXTERNAL')
        self.m.restore_latest()
        self.m.load_state(payload);self.w.refresh_summary()
        self.assertEqual(nature.current(self.w),'EXTERNAL')
        self.assertTrue(self.m.nature_controls['EXTERNAL'].isChecked())

    def test_changing_draft_nature_keeps_all_unsealed_price_versions_consistent(self):
        import quote_management_model as model
        self.choose('INTERNAL')
        model.append_version(self.m.state,self.w.draft_items,self.w.scheme2_company.currentText(),'合成调价版本','本机测试','2026-10-23')
        before=[entry['amount'] for entry in self.m.state['versions']]
        self.choose('EXTERNAL');self.save()
        self.assertTrue(all(entry['order_nature']=='EXTERNAL' for entry in self.m.state['versions']))
        self.assertEqual([entry['amount'] for entry in self.m.state['versions']],before)
        self.m.view_version(1)
        self.assertEqual(nature.current(self.w),'EXTERNAL')
        self.assertEqual(schemes._snapshot(self.w)['document']['order_nature'],'EXTERNAL')
        self.m.restore_latest()

    def test_old_formal_quote_opens_revision_for_classification_without_repricing(self):
        self.save();self.w._quote_scheme_status='QUOTED';self.w._quote_scheme_read_only=True
        self.m.state['versions'][-1]['sealed']=True
        old=schemes._snapshot(self.w)
        def opened(*args):
            schemes._apply_opened_scheme(self.w,dict(self.h.server,status='REVISING',version_no=2,snapshot=deepcopy(old)),route=ui.QUOTE_ROUTE)
        def run(window,method,path,payload,success,*args):
            if method=='GET':
                success(dict(items=[],total=0));return
            self.assertTrue(path.endswith('/revision'))
            success(dict(scheme_no=self.w._quote_scheme_id))
        with patch.object(schemes,'_run',run),patch.object(schemes,'_open_scheme',opened),patch.object(__import__('quote_management').AdjustQuoteDialog,'exec') as adjust:
            self.m.adjust()
            self.assertEqual(adjust.call_count,0)
        self.assertFalse(self.m.pending_adjust)
        self.assertEqual(self.w._quote_scheme_status,'REVISING')
        self.assertTrue(self.m.nature_controls['INTERNAL'].isEnabled())
        self.choose('INTERNAL');self.save()
        self.assertEqual(self.h.server['snapshot']['document']['order_nature'],'INTERNAL')
        self.assertEqual(ui._row_values(self.w.draft_items[0])[16],self.amount)

    def test_printer_error_does_not_register_or_freeze_a_draft(self):
        self.choose('INTERNAL');self.save()
        printer=QPrinter();dialog=Mock();dialog.exec.return_value=QDialog.DialogCode.Accepted
        with patch.object(ui,'QPrinter',Mock(return_value=printer,PrinterMode=QPrinter.PrinterMode)), \
             patch.object(ui,'QPrintDialog',return_value=dialog), \
             patch.object(ui.QTextDocument,'print_',return_value=None), \
             patch.object(printer,'printerState',return_value=QPrinter.PrinterState.Error), \
             patch.object(ui.QMessageBox,'warning') as warning:
            ui._print_quote(self.w)
            self.assertEqual(warning.call_count,1)
        self.assertEqual(self.h.posts(),[])
        self.assertIsNone(self.w._quote_scheme_pending_export)
        self.assertIsNone(self.w._quote_scheme_export_context)
        self.assertFalse(self.w._quote_scheme_read_only)

    def test_real_ui_classification_layout_at_desktop_sizes_and_contract_guard(self):
        self.w._scheme2_dirty=False;self.w.show()
        output=Path(os.environ.get('AI_QUOTE_ORDER_NATURE_SCREENSHOT_DIR', str(Path(__file__).resolve().parents[2]/'task-B-order-nature-handoff-20261023')))
        output.mkdir(parents=True, exist_ok=True)
        for width,height in ((1511,986),(1024,768)):
            self.w.resize(width,height);app.processEvents();self.m.root.setCurrentWidget(self.m.detail_page)
            self.assertEqual(self.m.tabs.count(),6)  # Existing five tabs plus the approved send log.
            for control in (*self.m.nature_controls.values(),self.m.save_button,self.m.discard_button):
                self.assertTrue(control.parentWidget().rect().contains(control.geometry()),control.objectName())
            field=self.w.scheme2_quote_company_field
            self.assertLessEqual(field.geometry().right(),self.m.nature_controls['INTERNAL'].geometry().left())
            if width==1511:
                for value in ('UNCLASSIFIED','INTERNAL','EXTERNAL'):
                    self.w._quote_order_nature=value;self.m.sync();self.w.refresh_summary();app.processEvents()
                    self.assertTrue(self.w.grab().save(str(output/('actual-ui-'+value.lower()+'.png'))))
        self.m.rows=[dict(scheme_no='BJ-20261023-900001',order_nature='INTERNAL',status='QUOTED',can_write=True)]
        self.m.list_table.setRowCount(1);self.m.list_table.selectRow(0);self.m.selection_changed()
        self.assertFalse(self.m.contract_button.isEnabled())
        before=self.w.stack.currentIndex();self.m.contract();self.assertEqual(self.w.stack.currentIndex(),before)
        self.m.rows[0]['order_nature']='EXTERNAL';self.m.selection_changed();self.assertTrue(self.m.contract_button.isEnabled())


if __name__=='__main__':unittest.main(verbosity=2)
