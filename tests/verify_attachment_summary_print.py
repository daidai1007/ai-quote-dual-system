"""Focused summary printing checks; no physical printer jobs are sent."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtGui import QFontDatabase, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import QApplication, QDialog, QToolButton
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['MainWindow'].refresh_formula_inputs = lambda self, *args: None
ns['ApiWorker'].run = lambda self: self.failed.emit('offline print test')


class SummaryPrintTests(unittest.TestCase):
    def setUp(self):
        self.window = ns['MainWindow']()
        attachments = [dict(custom=True, item_name=f'附件{i:02d}', quantity=1,
                            formula_amount=10, quick_amount=20) for i in range(32)]
        attachments.append(dict(item_name='安装板', attachment_price_id=101, quantity=2,
                                attachment_price_sign=-1, formula_amount=-30, quick_amount=-40))
        item = dict(name='产品<测试>&', product_code='JP', specification='(800+600)*600*(1800+100)',
                    quantity=1, attachments=attachments,
                    quick={'attachment_fee': 600, 'total_cost': 1000,
                           'matched_experience': {'items': [
                               {'reference_width_mm': 800, 'reference_depth_mm': 600, 'reference_height_mm': 1800},
                               {'reference_width_mm': 600, 'reference_depth_mm': 500, 'reference_height_mm': 1800}]}},
                    formula={'total_cost': 500}, quick_discount=.5)
        self.window.draft_items = [copy.deepcopy(item) for _ in range(40)]
        self.window.draft_items[-1]['name'] = '末行产品'
        self.window.refresh_summary()
        self.dialog = ui.AttachmentSummaryDialog(self.window)

    def tearDown(self):
        self.dialog.close()
        self.window.close()

    def printer(self, portrait=False):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait if portrait else QPageLayout.Orientation.Landscape)
        return printer

    def test_button_opens_native_settings_and_cancel_does_not_print(self):
        button = self.dialog.print_button
        close = self.dialog.findChild(QToolButton, 'scheme2AttachmentEditorClose')
        self.assertEqual(button.text(), '打印')
        self.assertEqual(button.height(), close.height())
        self.assertEqual(button.objectName(), 'scheme2PrimaryGhost')
        self.dialog.show()
        app.processEvents()
        self.assertLess(button.mapTo(self.dialog, button.rect().topRight()).x(), close.mapTo(self.dialog, close.rect().topLeft()).x())
        with patch.object(ui, 'QPrinter', return_value=self.printer()), patch.object(ui, 'QPrintDialog') as native, patch.object(ui.QTextDocument, 'print_') as spool:
            native.return_value.exec.return_value = QDialog.DialogCode.Rejected
            button.click()
            native.return_value.setWindowTitle.assert_called_once_with('打印附件汇总')
            self.assertTrue(native.return_value.setMinMax.called)
            spool.assert_not_called()
        output = ROOT / 'outputs/attachment-summary-print-button.png'
        self.assertTrue(self.dialog.grab().save(str(output)))

    def test_full_content_bands_pagination_and_pending_price(self):
        self.dialog.table.cellWidget(0, 5).lineEdit().setText('37.25')
        self.dialog._commit_print_edits()
        for portrait in (False, True):
            printer = self.printer(portrait)
            document = self.dialog._print_document(printer)
            plain = document.toPlainText()
            self.assertIn('产品<测试>&', plain)
            self.assertIn('末行产品', plain)
            self.assertIn('匹配尺寸', plain)
            self.assertIn('柜体1：800*600*1800', plain)
            self.assertIn('柜体2：600*500*1800', plain)
            self.assertIn('合计', plain)
            self.assertIn('附件明细', plain)
            self.assertIn('37.25', plain)
            self.assertIn('1,490.00', plain)
            self.assertIn('-80', plain)
            for i in range(32):
                self.assertIn(f'附件{i:02d}', plain)
            self.assertGreater(document.pageCount(), 2)
            tables = [frame for frame in document.rootFrame().childFrames() if hasattr(frame, 'columns')]
            self.assertGreater(len(tables), 3)
            self.assertTrue(all(table.format().headerRowCount() == 1 for table in tables))
            width = document.pageSize().width()
            self.assertTrue(all(document.documentLayout().frameBoundingRect(table).width() <= width + 1 for table in tables))
            page_height = document.pageSize().height()
            for table in tables:
                bounds = document.documentLayout().frameBoundingRect(table)
                self.assertEqual(int(bounds.top() / page_height), int((bounds.bottom() - 1) / page_height),
                                 'a table chunk must keep complete rows on one page')
                self.assertGreater(table.format().border(), 0)

    def test_accept_respects_final_paper_and_page_range(self):
        printer = self.printer()
        before = copy.deepcopy(self.window.draft_items)
        def accept():
            printer.setPageOrientation(QPageLayout.Orientation.Portrait)
            printer.setPrintRange(QPrinter.PrintRange.PageRange)
            printer.setFromTo(2, 3)
            return QDialog.DialogCode.Accepted
        with patch.object(ui, 'QPrinter', return_value=printer), patch.object(ui, 'QPrintDialog') as native, patch.object(ui.QTextDocument, 'print_') as spool:
            native.return_value.exec.side_effect = accept
            self.dialog.print_button.click()
            spool.assert_called_once_with(printer)
            self.assertEqual(printer.fromPage(), 2)
            self.assertEqual(printer.toPage(), 3)
            self.assertEqual(printer.pageLayout().orientation(), QPageLayout.Orientation.Portrait)
        self.assertEqual(self.window.draft_items, before)

    def test_empty_and_print_error(self):
        items = self.window.draft_items
        self.window.draft_items = []
        empty = ui.AttachmentSummaryDialog(self.window)
        self.assertFalse(empty.print_button.isEnabled())
        empty.close()
        self.window.draft_items = items
        with self.assertLogs(ui.LOGGER, level='ERROR'), patch.object(ui, 'QPrinter', return_value=self.printer()), patch.object(ui, 'QPrintDialog') as native, patch.object(ui.QTextDocument, 'print_', side_effect=RuntimeError('测试打印故障')), patch.object(ui.QMessageBox, 'warning') as warning:
            native.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.dialog.print_summary()
            self.assertIn('测试打印故障', warning.call_args.args[2])
            self.assertTrue(self.dialog.print_button.isEnabled())

    def test_invalid_range_sends_no_job(self):
        printer = self.printer()
        printer.setPrintRange(QPrinter.PrintRange.PageRange)
        printer.setFromTo(900, 999)
        with self.assertLogs(ui.LOGGER, level='ERROR'), patch.object(ui, 'QPrinter', return_value=printer), patch.object(ui, 'QPrintDialog') as native, patch.object(ui.QTextDocument, 'print_') as spool, patch.object(ui.QMessageBox, 'warning') as warning:
            native.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.dialog.print_summary()
            spool.assert_not_called()
            self.assertIn('页码', warning.call_args.args[2])


if __name__ == '__main__':
    if '--render-pdf' in sys.argv:
        case = SummaryPrintTests()
        case.setUp()
        printer = case.printer()
        output = ROOT / 'tmp/pdfs/attachment-summary-print-check.pdf'
        output.parent.mkdir(parents=True, exist_ok=True)
        printer.setOutputFileName(str(output))
        document = case.dialog._print_document(printer)
        document.print_(printer)
        pdf = ui.PdfReader(output)
        assert len(pdf.pages) == document.pageCount()
        pages = [page.extract_text() for page in pdf.pages]
        assert all('产品报价' in page or '附件明细' in page for page in pages)
        assert sum(page.count('末行产品') for page in pages) == document.toPlainText().count('末行产品')
        assert all(f'附件{i:02d}' in ''.join(pages) for i in range(32))
        case.tearDown()
        print(output)
    else:
        unittest.main()
