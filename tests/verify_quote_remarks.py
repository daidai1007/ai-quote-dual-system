"""Real V3 remark editing, popup names, snapshots, PDF and XLSX; fake data only."""
from copy import deepcopy
import html
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import verify_quote_export_customer as fixture
from verify_quote_document_progress import app, wait, ui, ns
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPlainTextEdit, QDialog
import quote_scheme_center as schemes
import quote_management_model as versions

OUT=Path(os.environ.get('AI_QUOTE_REMARK_SCREENSHOT_DIR',str(fixture.ROOT/'test-output/quote-remarks')))


class QuoteRemarks(unittest.TestCase):
    clean_window=fixture.ExportCustomer.clean_window
    export=fixture.ExportCustomer.export
    posts=fixture.ExportCustomer.posts

    def setUp(self):
        screen=Mock(wraps=app.primaryScreen());screen.availableGeometry.return_value=QRect(0,0,4096,2160)
        p=patch.object(ns['MainWindow'],'screen',return_value=screen);p.start();self.addCleanup(p.stop)
        fixture.ExportCustomer.setUp(self)
        self.w=self.window
        item=self.w.draft_items[0]
        for field in ('final_remark','notes','source_ocr_remark','source_reviewed_remark','quote_remark_manual'):
            item.pop(field,None)
        item['attachments']=[
            dict(item_name='风机',model_code='MODEL-NOT-IN-REMARK',width_mm=120,height_mm=120,depth_mm=40,
                 quantity=3,status='FIXED',formula_amount=6,quick_amount=12,attachment_price_id=9),
            dict(item_name='风机',model_code='SECOND-MODEL',quantity=2,status='FIXED',
                 formula_amount=4,quick_amount=8,attachment_price_id=10),
            dict(item_name='照明灯',category_level1='照明灯/行程开关',specification='照明灯220V长款',quantity=1,
                 status='FIXED',formula_amount=3,quick_amount=6,attachment_price_id=11),
            dict(item_name='人工附加件',custom=True,quantity=1,formula_amount=2,custom_cost=2,
                 quick_amount=4,unit_price_override=4),
        ]
        item['attachment_snapshot_dirty']=False
        self.w.refresh_summary();self.w._quote_scheme_save_timer.stop()
        self.w.resize(1560,960);self.w.show();self.m.show_detail();app.processEvents()

    def edit(self,text,commit=True):
        table=self.w.scheme2_quote_preview
        table.scrollToItem(table.item(10,7));table.editItem(table.item(10,7));app.processEvents()
        editor=next((child for child in table.findChildren(QPlainTextEdit,'scheme2QuoteRemarkEditor') if child.isVisible()),None)
        self.assertIsNotNone(editor);editor.setFocus();editor.setPlainText(text)
        if commit:
            QTest.keyClick(editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier);app.processEvents()
        return editor

    def screenshot(self,name):
        OUT.mkdir(parents=True,exist_ok=True);app.processEvents()
        self.assertTrue(self.w.grab().save(str(OUT/name)))

    def assert_outputs(self,value):
        self.w._quote_scheme_save_timer.stop()
        expected_prices=ui._row_values(self.w.draft_items[0])[15:17]
        self.export()
        self.assertTrue(self.path.exists(),self.messages)
        for sheet in ('报价','成本'):
            self.assertEqual(fixture.workbook_cell(self.path,sheet,'H11'),value)
        for _url,payload in self.requests:
            if 'items' in payload:
                row=payload['items'][0]
                self.assertEqual(row['quote_display']['remark'],value)
                for field in ('final_remark','notes','source_ocr_remark','source_reviewed_remark'):
                    self.assertEqual(row[field],value)
        saved=self.posts()[-1]['snapshot']
        self.assertEqual(saved['draft_items'][0]['final_remark'],value)
        self.assertEqual(saved['quote_management']['versions'][-1]['items'][0]['final_remark'],value)
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15:17],expected_prices)
        return saved

    def test_default_names_models_and_per_cabinet_quantities_match_popup_rows(self):
        item=self.w.draft_items[0]
        dialog=ui.AttachmentEditor(self.w,item)
        names=list(dict.fromkeys(dialog.table.item(row,0).text() for row in range(dialog.table.rowCount())))
        self.assertEqual(names,['风机','照明灯/行程开关','人工附加件'])
        dialog.accept()
        actual=self.w.scheme2_quote_preview.item(10,7).text()
        self.assertEqual(item['quantity'],2)
        for included in ('配MODEL-NOT-IN-REMARK风机3只','配SECOND-MODEL风机2只',
                         '配照明灯220V长款1套','配人工附加件1件'):
            self.assertIn(included,actual)
        self.assertNotIn('120',actual)  # Not an explicit requested specification.
        dialog=ui.AttachmentEditor(self.w,item)
        dialog.table.item(0,0).setText('弹窗更名附件')
        dialog.table.cellWidget(0,dialog.COL_QUANTITY).setValue(4)
        dialog.table.removeRow(1);dialog.accept()
        self.assertIn('弹窗更名附件4件',self.w.scheme2_quote_preview.item(10,7).text())
        self.assertNotIn('风机',self.w.scheme2_quote_preview.item(10,7).text())
        self.screenshot('01-default-popup-names.png')

    def test_popup_per_cabinet_quantities_save_reopen_print_and_export(self):
        item=self.w.draft_items[0];item['quantity']=7
        dialog=ui.AttachmentEditor(self.w,item)
        dialog.table.cellWidget(0,dialog.COL_QUANTITY).setValue(4)
        dialog.table.cellWidget(3,dialog.COL_QUANTITY).setValue(6)
        dialog.accept();self.w._quote_scheme_save_timer.stop()
        expected=self.w.scheme2_quote_preview.item(10,7).text()
        for phrase in ('风机4只','风机2只','照明灯220V长款1套','人工附加件6件'):
            self.assertIn(phrase,expected)
        self.assertEqual(item['attachments'][0]['quantity'],4)
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(self.server['snapshot']['draft_items'][0]['final_remark'],expected)
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        pdf=Path(self.folder.name)/'attachment-counts.pdf'
        def choose(dialog):
            printer=dialog.printer();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        from pypdf import PdfReader
        printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
        for phrase in ('风机4只','风机2只','人工附加件6件'):
            self.assertIn(phrase,printed)
        self.assertEqual(self.posts()[-1]['kind'],'PRINT')
        self.assert_outputs(expected)
        self.screenshot('04-attachment-quantities.png')

    def test_ganged_and_negative_board_counts_match_popup_without_cancelling_rows(self):
        item=self.w.draft_items[0];item['quantity']=9
        item['ganged_cabinet_count']=2
        item['attachments']=[
            dict(item_name='内门',ganged_inner_door_match=True,ganged_cabinet_index=0,quantity=2),
            dict(item_name='内门',ganged_inner_door_match=True,ganged_cabinet_index=1,quantity=3),
            dict(item_name='安装板',quantity=2,attachment_price_sign=-1),
            dict(item_name='安装板',quantity=1,attachment_price_sign=1),
            dict(item_name='安装板',quantity=-3),
        ]
        before=deepcopy(item)
        dialog=ui.AttachmentEditor(self.w,item)
        counts=[dialog.table.cellWidget(r,dialog.COL_QUANTITY).value() for r in range(dialog.table.rowCount())]
        self.assertEqual(counts,[2,3,-2,1,-3])
        actual=ui._scheme2_quote_remark(item)
        for phrase in ('内门2件（柜体1，单台）','内门3件（柜体2，单台）',
                       '扣减2.5mm镀锌安装板2块（每组）','配2.5mm镀锌安装板1块（每组）','扣减2.5mm镀锌安装板3块（每组）'):
            self.assertIn(phrase,actual)
        self.assertNotIn('不含安装板',actual)
        self.assertEqual(item['attachments'],before['attachments'])
        dialog.reject()

    def test_cost_page_order_count_change_does_not_change_per_cabinet_remarks(self):
        item=self.w.draft_items[0];attachments=deepcopy(item['attachments'])
        expected=self.w.scheme2_quote_preview.item(10,7).text()
        self.w.summary_table.item(0,4).setText('5');app.processEvents()
        self.assertEqual(item['quantity'],5)
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        self.assertEqual(item['attachments'],attachments)
        self.w.refresh_summary();self.w.refresh_summary()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        self.w.summary_table.item(0,4).setText('2');app.processEvents()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),expected)
        self.assertEqual(item['attachments'],attachments)

    def test_historical_default_keeps_per_cabinet_counts(self):
        item=self.w.draft_items[0];item['quantity']=2;self.w.refresh_summary()
        first=deepcopy(self.w.draft_items)
        item['quantity']=5;self.w.refresh_summary()
        self.m.state['versions']=[versions.make_version(first,'合成测试客户',1,'首次','合成人员','2026-10-26'),
                                  versions.make_version(self.w.draft_items,'合成测试客户',2,'修订','合成人员','2026-10-26')]
        self.m.view_version(1)
        for actual in (self.w.scheme2_quote_preview.item(10,7).text(),ui._printable_quote_html(self.w),
                       ui._quote_export_items_snapshot(self.w)[0]['quote_display']['remark']):
            self.assertIn('风机3只',actual)
            self.assertIn('风机2只',actual)
        self.m.restore_latest();self.w._quote_scheme_save_timer.stop()
        self.assertIn('风机3只',self.w.scheme2_quote_preview.item(10,7).text())

    def test_old_names_only_and_current_auto_text_remain_automatic(self):
        item=self.w.draft_items[0]
        for prior in (ui._scheme2_quote_remark(item,include_quantities=False),ui._scheme2_quote_remark(item)):
            item.pop('quote_remark_manual',None);ui._synchronize_export_remark(item,prior)
            self.assertIn('风机3只',ui._quote_item_remark(item))
            self.assertFalse(item['quote_remark_manual'])
        dialog=ui.AttachmentEditor(self.w,item)
        dialog.table.cellWidget(0,dialog.COL_QUANTITY).setValue(8);dialog.accept()
        self.assertIn('风机8只',self.w.scheme2_quote_preview.item(10,7).text())

    def test_full_manual_text_saves_reopens_prints_and_exports(self):
        text='人工备注：附件按双方确认内容交付 <A>&B\n第二行可以修改整段说明。'
        prices=ui._row_values(self.w.draft_items[0])[15:17]
        self.edit(text)
        self.assertEqual(self.w.draft_items[0]['final_remark'],text)
        self.assertTrue(self.w.draft_items[0]['quote_remark_manual'])
        self.assertEqual(ui._row_values(self.w.draft_items[0])[15:17],prices)
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        saved=deepcopy(self.server['snapshot'])
        self.w.draft_items=[]
        schemes._apply_opened_scheme(self.w,dict(found=True,**deepcopy(self.server),quote_management_historical_export=True),ui.QUOTE_ROUTE)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),text)
        self.assertEqual(saved['draft_items'][0]['final_remark'],text)
        rendered=ui._printable_quote_html(self.w)
        self.assertIn(html.escape(text).replace('\n','<br>'),rendered)
        pdf=Path(self.folder.name)/'artificial-remark.pdf'
        printer=QPrinter(QPrinter.PrinterMode.HighResolution);printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
        document=QTextDocument();document.setHtml(rendered);document.print_(printer)
        from pypdf import PdfReader
        printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
        self.assertIn('第二行可以修改整段说明',printed)
        self.assert_outputs(text);self.screenshot('02-manual-remark.png')

    def test_empty_manual_remark_stays_empty_after_refresh_and_export(self):
        self.edit('')
        self.w.refresh_summary()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),'')
        self.assert_outputs('')

    def test_pending_editor_is_committed_before_export_freezes_receipt(self):
        self.edit('尚在编辑时直接导出的人工备注',commit=False)
        self.assert_outputs('尚在编辑时直接导出的人工备注')

    def test_pending_editor_is_saved_and_real_print_route_uses_latest_text(self):
        self.edit('仍在编辑时保存的备注',commit=False)
        self.m.save();wait(lambda:self.w._quote_scheme_save_worker is None)
        self.assertEqual(self.server['snapshot']['draft_items'][0]['final_remark'],'仍在编辑时保存的备注')
        self.edit('仍在编辑时打印的备注',commit=False)
        pdf=Path(self.folder.name)/'actual-print-route.pdf'
        def choose(dialog):
            printer=dialog.printer();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat);printer.setOutputFileName(str(pdf))
            return QDialog.DialogCode.Accepted
        with patch.object(ui.QPrintDialog,'exec',choose):self.w.scheme2_quote_print.click()
        wait(lambda:not self.w._quote_scheme_workers)
        from pypdf import PdfReader
        printed=''.join(''.join(page.extract_text() for page in PdfReader(pdf).pages).split())
        self.assertIn('仍在编辑时打印的备注',printed)
        self.assertEqual(self.posts()[-1]['kind'],'PRINT')
        self.assertEqual(self.posts()[-1]['snapshot']['draft_items'][0]['final_remark'],'仍在编辑时打印的备注')

    def test_legacy_auto_text_updates_but_existing_manual_and_sealed_text_survive(self):
        item=self.w.draft_items[0]
        legacy=ui._scheme2_quote_remark(item,legacy=True)
        item.pop('quote_remark_manual');ui._synchronize_export_remark(item,legacy)
        self.assertIn('照明灯220V长款',ui._quote_item_remark(item))
        self.assertFalse(item['quote_remark_manual'])
        item.pop('quote_remark_manual');ui._synchronize_export_remark(item,'原有人工备注')
        self.assertEqual(ui._quote_item_remark(item),'原有人工备注')
        self.assertTrue(item['quote_remark_manual'])
        item.pop('quote_remark_manual');ui._synchronize_export_remark(item,legacy)
        self.w._quote_scheme_read_only=True;self.w.refresh_summary()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),legacy)
        self.assertNotIn('quote_remark_manual',item)

    def test_manual_override_survives_popup_changes_and_escape_cancels(self):
        self.edit('手工保留的整段附件说明')
        dialog=ui.AttachmentEditor(self.w,self.w.draft_items[0]);dialog.table.item(0,0).setText('修改过的附件名称')
        dialog.table.cellWidget(0,dialog.COL_QUANTITY).setValue(9);dialog.accept()
        self.w.summary_table.item(0,4).setText('4');app.processEvents()
        self.assertEqual(self.w.scheme2_quote_preview.item(10,7).text(),'手工保留的整段附件说明')
        editor=self.edit('应该取消的内容',commit=False);QTest.keyClick(editor,Qt.Key.Key_Escape);app.processEvents()
        self.assertEqual(self.w.draft_items[0]['final_remark'],'手工保留的整段附件说明')

    def test_readonly_history_and_other_person_cannot_edit_remarks(self):
        self.edit('历史原备注')
        first=deepcopy(self.w.draft_items)
        self.edit('最新备注')
        self.m.state['versions']=[versions.make_version(first,'合成测试客户',1,'首次','合成人员','2026-10-23'),
                                  versions.make_version(self.w.draft_items,'合成测试客户',2,'修订','合成人员','2026-10-23')]
        self.m.view_version(1)
        cell=self.w.scheme2_quote_preview.item(10,7)
        self.assertFalse(cell.flags()&Qt.ItemFlag.ItemIsEditable)
        cell.setText('禁止改写');self.assertEqual(self.w.draft_items[0]['final_remark'],'历史原备注')
        self.m.restore_latest();self.w._quote_scheme_save_timer.stop()
        wait(lambda:self.w._quote_scheme_save_worker is None)
        self.w._name_scope_foreign=True;self.w.refresh_summary()
        cell=self.w.scheme2_quote_preview.item(10,7)
        self.assertFalse(cell.flags()&Qt.ItemFlag.ItemIsEditable)
        cell.setText('禁止改写');self.assertEqual(self.w.draft_items[0]['final_remark'],'最新备注')
        self.w._name_scope_foreign=False

    def test_editor_fits_normal_and_narrow_windows(self):
        for width,height in ((1560,960),(1280,860),(1024,768)):
            self.w.resize(width,height);app.processEvents()
            editor=self.edit('只展示附件名称；这是一段可以换行的人工备注。\n第二行备注。',commit=False)
            table=self.w.scheme2_quote_preview
            self.assertTrue(table.viewport().rect().contains(editor.geometry()))
            self.assertTrue(editor.hasFocus())
            self.screenshot(f'03-editing-{width}.png')
            QTest.keyClick(editor,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier);app.processEvents()


if __name__=='__main__':unittest.main(verbosity=2)
