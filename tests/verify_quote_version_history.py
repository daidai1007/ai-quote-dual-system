"""Repeated repricing through the actual Qt controller, offline synthetic records."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
import os
import unittest

import verify_quote_export_customer as fixture
from verify_quote_document_progress import app, wait, ui, QTimer
from PySide6.QtWidgets import QDialog, QPushButton
from PySide6.QtCore import QRect
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtGui import QTextDocument
from pypdf import PdfReader
import quote_management as qm
import quote_management_model as model
import quote_scheme_center as schemes
from verify_quote_management import items as discount_items


class VersionHistoryTests(unittest.TestCase):
    def setUp(self):
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        screen_patch=patch.object(fixture.registration.base.Window,'screen',return_value=screen)
        screen_patch.start();self.addCleanup(screen_patch.stop)
        self.h = fixture.ExportCustomer(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.w = self.h.window; self.m = self.w.quote_management
        self.w._scheme2_loading_order = False
        self.w._quote_scheme_loading = True
        self.w.draft_items[0]['name'] = '合成版本测试柜'
        self.w.scheme2_company.setEditText('合成历史测试客户')
        self.m.sync(); self.w.refresh_summary()
        self.w._quote_scheme_loading = False
        self.h.server.update(snapshot=deepcopy(schemes._snapshot(self.w)), quote_management_historical_export=True)
        self.w._quote_scheme_save_timer.stop()
        prior = schemes.QuoteSchemeWorker.start
        def start(worker):
            if (worker.method == 'POST' and worker.url.endswith('/export-result')
                    and worker.payload.get('historical_quote_version')):
                worker.test_running=True
                self.h.scheme_requests.append((worker.method,worker.url,deepcopy(worker.payload)))
                def recorded():
                    worker.test_running=False
                    worker.succeeded.emit(dict(recorded=True,formal_success=True,historical=True,
                        status=self.h.server['status'],lock_version=self.h.server['lock_version']))
                    worker.finished.emit()
                QTimer.singleShot(1,recorded)
                return
            if not (worker.method == 'POST' and worker.url.endswith('/revision')):
                return prior(worker)
            worker.test_running = True
            self.h.scheme_requests.append((worker.method, worker.url, deepcopy(worker.payload)))
            assert worker.payload['expected_version'] == self.h.server['lock_version']
            assert self.h.server['status'] == 'QUOTED'
            self.h.server.update(status='REVISING', version_no=self.h.server['version_no']+1,
                                 lock_version=self.h.server['lock_version']+1)
            self.h.server['snapshot']['document']['version_no'] = self.h.server['version_no']
            def respond():
                worker.test_running=False
                worker.succeeded.emit(deepcopy(self.h.server)); worker.finished.emit()
            QTimer.singleShot(1, respond)
        p=patch.object(schemes.QuoteSchemeWorker, 'start', start);p.start();self.addCleanup(p.stop)

    def adjust(self, price, reason):
        def edit(dialog):
            dialog.grid.item(0, 2).setText(str(price))
            dialog.reason.setPlainText(reason)
            return QDialog.DialogCode.Accepted
        with patch.object(qm.AdjustQuoteDialog, 'exec', edit):
            self.m.adjust()
            wait(lambda:not self.w._quote_scheme_workers and not self.m.pending_adjust)
        self.w._quote_scheme_save_timer.stop()

    def reopen(self):
        schemes._apply_opened_scheme(self.w, deepcopy(self.h.server), 2)
        self.w._quote_scheme_save_timer.stop()

    def test_cancelled_formal_revision_is_not_history_until_confirmed(self):
        self.m.save(); wait(lambda:not self.w._quote_scheme_workers)
        self.h.export(); self.reopen()
        with patch.object(qm.AdjustQuoteDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            self.m.adjust(); wait(lambda:not self.w._quote_scheme_workers and not self.m.pending_adjust)
        self.assertTrue(self.m.state['versions'][-1].get('revision_draft'))
        self.assertEqual(self.m.history.rowCount(),1)
        # Existing quote sheet supports directly editing the discounted unit price.
        self.w.scheme2_quote_preview.item(10, 5).setText('502.00')
        self.m.save(); wait(lambda:not self.w._quote_scheme_workers)
        self.reopen()
        self.assertEqual(self.m.history.rowCount(),1)
        saved_v1=deepcopy(self.m.state['versions'][0])
        self.assertFalse(schemes._prepare_export(self.w))
        self.adjust(502, '确认本轮调价')
        self.assertEqual(len(self.m.state['versions']),2)
        self.assertEqual(self.m.history.rowCount(),2)
        self.assertEqual(self.m.state['versions'][0],saved_v1)
        self.assertTrue(self.m.state['versions'][-1]['confirmed'])
        self.assertEqual(ui._row_values(self.m.state['versions'][-1]['items'][0])[15],502)

    def test_repeated_formal_revisions_retain_all_versions(self):
        self.m.save(); wait(lambda:not self.w._quote_scheme_workers)
        self.h.export(); self.reopen()
        previous = deepcopy(self.m.state['versions'])
        for number in range(2, 7):
            self.adjust(500 + number, f'第{number}版合成调价')
            self.assertEqual(len(self.m.state['versions']),number, self.m.state)
            self.assertEqual([v['version'] for v in self.m.state['versions']],list(range(1,number+1)))
            self.assertEqual(self.m.state['versions'][-1]['reason'],f'第{number}版合成调价')
            self.assertEqual(self.m.state['versions'][:-1],previous)
            self.h.export(); self.reopen()
            self.assertEqual(self.m.history.rowCount(),number)
            self.assertEqual(self.m.state['versions'][-1]['reason'],f'第{number}版合成调价')
            self.assertEqual(self.m.state['versions'][:-1],previous)
            previous=deepcopy(self.m.state['versions'])

    def test_repeated_unexported_adjustments_survive_reopen_and_compare(self):
        previous=deepcopy(self.m.state['versions'])
        for number in range(2,9):
            self.adjust(500+number,f'未导出第{number}次议价')
            self.assertEqual(self.h.server['snapshot']['quote_management']['current'],number)
            self.assertEqual(self.m.state['versions'][:-1],previous)
            previous=deepcopy(self.m.state['versions']); self.reopen()
            self.assertEqual(self.m.state['versions'],previous)
        self.m.from_version.setCurrentIndex(self.m.from_version.findData(2))
        self.m.to_version.setCurrentIndex(self.m.to_version.findData(8));self.m.compare()
        self.assertEqual(self.m.compare_table.item(0,3).text(),'502.00')
        self.assertEqual(self.m.compare_table.item(0,4).text(),'508.00')
        self.assertIn('金额：+12.00',self.m.compare_table.item(0,5).text())
        self.assertIn('毛利率：',self.m.compare_table.item(0,5).text())
        self.w.resize(1519,987);self.w.show();self.m.tabs.setCurrentWidget(self.m.history)
        app.processEvents()
        self.assertEqual(len(self.m.history.findChildren(QPushButton)),8)
        self.assertEqual(self.m.history.item(0,0).text(),'V1')
        output=Path(os.environ.get('AI_QUOTE_VERSION_SCREENSHOT_DIR',str(fixture.ROOT/'outputs'/'quote-version-history')))
        output.mkdir(parents=True,exist_ok=True)
        self.assertTrue(self.w.grab().save(str(output/'eight-versions.png')))

    def test_discount_and_attachment_changes_only_commit_on_final_confirmation(self):
        self.w._quote_scheme_loading=True
        self.w.draft_items=discount_items();self.w._qm_state=model.restore_state(None)
        self.m.generated();self.w.refresh_summary();self.w._quote_scheme_loading=False
        self.w._quote_scheme_save_timer.stop()
        for number in (2,3):
            errors=[];qt_errors=[]
            def edit():
                dialog=self.m.root.currentWidget()
                try:
                    self.assertIsInstance(dialog,qm.AdjustQuoteDialog)
                    if number==2:dialog.grid.item(0,5).setText('0.8')
                    else:
                        dialog.attachment_row(0)
                        from PySide6.QtWidgets import QTableWidget
                        grid=dialog.attachment_panel.findChild(QTableWidget)
                        dialog.change_attachment(0,0,'100',grid)
                        self.assertEqual(dialog.items[0]['attachments'][1]['quick_amount'],50)
                    dialog.reason.setPlainText(f'确认第{number}轮')
                    dialog.accept()
                    self.assertTrue(dialog.reviewing)
                    self.assertEqual(len(self.m.state['versions']),number-1)
                    dialog.accept()
                except Exception as error:
                    errors.append(error);dialog.reject()
            with patch('sys.excepthook',side_effect=lambda kind,error,trace:qt_errors.append(error)):
                QTimer.singleShot(0,edit);self.m.adjust()
            self.assertFalse(errors,errors)
            self.assertFalse(qt_errors,qt_errors)
            wait(lambda:not self.w._quote_scheme_workers);self.w._quote_scheme_save_timer.stop()
            self.assertEqual(self.m.state['current'],number)
            self.assertTrue(self.m.state['versions'][-1]['confirmed'])
        self.assertEqual([v['amount'] for v in self.m.state['versions']],[4004,3668,3620])
        self.assertEqual([v['items'][0]['quick_discount'] for v in self.m.state['versions']],[.9,.8,.8])
        self.reopen()
        self.assertEqual([v['amount'] for v in self.m.state['versions']],[4004,3668,3620])

    def test_legacy_saved_edited_revision_flag_is_migrated_without_replacing_price(self):
        self.m.save();wait(lambda:not self.w._quote_scheme_workers);self.h.export();self.reopen()
        state=deepcopy(self.m.state)
        changed=deepcopy(self.w.draft_items);model.set_unit_price(changed[0],'502')
        entry=model.append_version(state,changed,self.w.scheme2_company.currentText(),'旧客户端已保存调价','旧操作人')
        entry['revision_draft']=True
        self.h.server.update(status='REVISING',version_no=2)
        self.h.server['snapshot'].update(draft_items=changed,quote_management=state)
        self.reopen()
        self.assertNotIn('revision_draft',self.m.state['versions'][-1])
        self.adjust(503,'新一轮')
        self.assertEqual(len(self.m.state['versions']),3)
        self.assertEqual(self.m.state['versions'][1]['operator'],'旧操作人')
        self.assertEqual(ui._row_values(self.m.state['versions'][1]['items'][0])[15],502)

    def test_over_100_versions_reopen_view_print_and_real_excel(self):
        # Cross both former limits: client 50, list API two-digit numbering.
        for number in range(2,121):
            changed=deepcopy(self.w.draft_items);model.set_unit_price(changed[0],str(500+number))
            model.append_version(self.m.state,changed,self.w.scheme2_company.currentText(),f'第{number}轮','本机合成人员',self.w._quote_scheme_quote_date)
        self.w.draft_items=deepcopy(self.m.state['versions'][-1]['items'])
        self.m.save();wait(lambda:not self.w._quote_scheme_workers);self.reopen()
        self.assertEqual(self.m.history.rowCount(),120)
        old=deepcopy(self.m.state['versions']);self.adjust(621,'第121轮')
        self.assertEqual(self.m.state['versions'][:-1],old)
        self.assertEqual(self.m.state['current'],121)
        self.h.export();self.reopen()
        frozen=deepcopy(self.h.server['snapshot'])
        for number in (1,51,100,121):
            with self.subTest(version=number):
                self.m.view_version(number)
                price=ui._row_values(self.m.state['versions'][number-1]['items'][0])[15]
                self.assertEqual(ui._quote_export_items_snapshot(self.w)[0]['quote_display']['unit_price'],price)
                destination=Path(self.h.folder.name)/f'v{number}.pdf'
                printer=QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(destination))
                document=QTextDocument();document.setHtml(ui._printable_quote_html(self.w));document.print_(printer)
                text=''.join(page.extract_text() for page in PdfReader(str(destination)).pages)
                self.assertIn(f'{price:,.2f}',text)
                self.h.export()
                self.assertEqual(float(fixture.workbook_cell(self.h.path,'报价','F11')),price)
                self.assertEqual(float(fixture.workbook_cell(self.h.path,'报价','G11')),price*2)
                self.assertEqual(self.h.server['snapshot'],frozen)
                self.m.restore_latest()

    def test_cancel_no_change_and_failed_save_do_not_drop_existing_versions(self):
        self.adjust(502,'第一次调价')
        saved_formula=self.m.state['versions'][-1]['items'][0]['formula']
        for key in ('manufacturing_cost','manufacturing_quote_unit_price','management_fee','tax_cost','total_cost'):
            self.assertEqual(saved_formula[key],self.w.draft_items[0]['formula'][key],key)
        self.assertEqual(saved_formula['manufacturing_quote_unit_price'],502)
        before=deepcopy(self.m.state)
        with patch.object(qm.AdjustQuoteDialog,'exec',return_value=QDialog.DialogCode.Rejected):self.m.adjust()
        self.assertEqual(self.m.state,before)
        self.adjust(502,'没有金额变化')
        self.assertEqual(self.m.state,before)
        prior=schemes.QuoteSchemeWorker.start
        def fail(worker):
            if worker.method!='PUT':return prior(worker)
            worker.test_running=True
            def respond():
                worker.test_running=False;worker.failed.emit('合成保存中断');worker.finished.emit()
            QTimer.singleShot(1,respond)
        with patch.object(schemes.QuoteSchemeWorker,'start',fail):self.adjust(503,'保存失败待重试')
        self.assertEqual(self.m.state['versions'][:2],before['versions'])
        self.assertEqual(len(self.m.state['versions']),3)
        self.assertEqual(self.h.server['snapshot']['quote_management']['current'],2)
        self.m.save();wait(lambda:not self.w._quote_scheme_workers);self.reopen()
        self.assertEqual(self.m.state['current'],3)
        self.assertEqual(self.m.state['versions'][:2],before['versions'])

    def test_ordinary_edits_only_get_a_version_when_adjustment_is_confirmed(self):
        self.adjust(502,'第一轮确认')
        confirmed=deepcopy(self.m.state)
        self.w.scheme2_quote_preview.item(10,5).setText('503.00')
        self.m.save();wait(lambda:not self.w._quote_scheme_workers)
        self.assertEqual(self.m.state,confirmed)
        self.reopen()
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15],503)
        self.assertEqual(ui._row_values(self.m.state['versions'][1]['items'][0])[15],502)
        self.assertFalse(schemes._prepare_export(self.w))
        self.assertIn('未确认修改',self.h.information[-1])
        self.m.view_version(2)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15],502)
        self.assertTrue(self.w._quote_scheme_read_only)
        self.h.export()
        self.assertEqual(float(fixture.workbook_cell(self.h.path,'报价','F11')),502)
        self.assertEqual(self.h.server['snapshot']['draft_items'][0]['quick_discount'],self.m.latest_workspace['items'][0]['quick_discount'])
        self.m.restore_latest()
        # Confirmation records the staged edit even when the dialog needs no
        # additional changes; cancellation must retain both earlier records.
        with patch.object(qm.AdjustQuoteDialog,'exec',return_value=QDialog.DialogCode.Rejected):self.m.adjust()
        self.assertEqual(self.m.state,confirmed)
        self.adjust(503,'确认单价修改')
        self.assertEqual(self.m.state['current'],3)
        self.assertEqual(self.m.state['versions'][:2],confirmed['versions'])


if __name__ == '__main__': unittest.main(verbosity=2)
