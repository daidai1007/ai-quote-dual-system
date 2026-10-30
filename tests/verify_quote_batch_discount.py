"""Actual Qt product-batch pricing, offline saves and real XLSX output.

Synthetic products/customers only; no installed client, live API or database.
"""
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import verify_quote_management as fixture
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QTableWidget
from quote_scheme_widgets import LIGHT_ACTION

APP, ui, qm, model = fixture.APP, fixture.ui, fixture.qm, fixture.model


def batch_items():
    first, other = fixture.items()
    first['scheme2_selected_product_name'] = 'JS'
    second = deepcopy(first)
    second.update(name='合成同产品第二柜', product_code='JS_DIFFERENT_SIZE',
                  specification='800*600*1600', quantity=1, quick_discount=.75)
    second['quick'].update(base_price=800, total_cost=970)
    other['scheme2_selected_product_name'] = 'JE'
    return [first, second, other]


class BatchDiscountTests(unittest.TestCase):
    setUp = fixture.ManagementTests.setUp
    tearDown = fixture.ManagementTests.tearDown

    def dialog(self, items=None):
        dialog = qm.AdjustQuoteDialog(batch_items() if items is None else items, 2, self.w)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def apply(self, dialog, value, product='JS'):
        dialog.batch_product.setCurrentIndex(dialog.batch_product.findData(product))
        dialog.batch_factor.setText(str(value)); dialog.batch_apply.click()

    def test_product_group_matches_cost_page_and_selection_never_reprices(self):
        d = self.dialog()
        self.assertEqual([d.batch_product.itemData(i) for i in range(d.batch_product.count())], ['JS','JE'])
        self.assertEqual(d.batch_scope.text(), 'JS · 2 项 / 4 台')
        self.assertEqual(d.batch_rows(), [0,1])
        self.assertIn('JS ·', d.grid.cellWidget(0,0).findChildren(fixture.qm.QLabel)[0].text())
        # Preserve a full-precision factor from direct unit-price editing.
        d.grid.item(0,2).setText('1000.01')
        before = deepcopy(d.items)
        d.batch_product.setCurrentIndex(1)
        self.assertEqual(d.batch_rows(), [2]); self.assertEqual(d.items, before)
        self.assertTrue(d.grid.cellWidget(2,2).property('batchMatch'))
        self.assertFalse(d.grid.cellWidget(0,2).property('batchMatch'))
        d.batch_product.setCurrentIndex(0)
        self.assertEqual(d.items, before)
        self.assertEqual(d.grid.item(0,4).text(), '0.9')
        self.assertEqual(d.batch_product.accessibleName(), '批量调价产品')

    def test_batch_replaces_factor_and_preserves_original_prices_and_costs(self):
        source = batch_items(); before = deepcopy(source); d = self.dialog(source)
        self.apply(d, .5)
        self.assertEqual([i['quick_discount'] for i in d.items], [.5,.5,.8])
        self.assertEqual([ui._row_values(i)[15] for i in d.items], [620,520,400])
        self.assertEqual([ui._row_values(i)[16] for i in d.items], [1860,520,800])
        self.assertIn('3,180.00', d.total.text())
        self.assertEqual([i['quote_original_discount'] for i in d.items], [.9,.75,.8])
        for n,item in enumerate(d.items):
            self.assertEqual(item['attachments'], before[n]['attachments'])
            self.assertEqual(item['formula'], before[n]['formula'])
            self.assertEqual(item['quantity'], before[n]['quantity'])
        self.assertEqual(d.items[2], d.original_items[2])
        self.assertEqual(source, before)
        # A repeated application replaces .5 with .4 rather than multiplying.
        self.apply(d, .4)
        self.assertEqual([ui._row_values(i)[15] for i in d.items], [508,428,400])
        self.assertIn('2,752.00', d.total.text())
        self.assertIn('已将 2 项 JS', d.batch_feedback.text())

    def test_invalid_batch_is_atomic_and_existing_invalid_fields_are_protected(self):
        d = self.dialog(); before = deepcopy(d.items)
        for text in ('', 'nan', 'inf', '-1', '0.12345', '10.01'):
            self.apply(d, text)
            self.assertEqual(d.items,before); self.assertTrue(d.error.text())
        d.grid.item(2,5).setText('invalid')
        self.apply(d,.5)
        self.assertEqual(d.items,before); self.assertIn('其他产品',d.error.text())
        d.grid.item(2,5).setText('0.8')
        d.grid.item(0,2).setText('1')  # below locked accessories + freight
        self.assertTrue(d.errors)
        self.apply(d,.5)
        self.assertFalse(d.errors); self.assertEqual(d.grid.item(0,2).text(),'620.00')
        d.attachment_row(0); grid=d.attachment_panel.findChild(QTableWidget)
        d.change_attachment(0,0,'bad',grid)
        before=deepcopy(d.items); self.apply(d,.6)
        self.assertEqual(d.items,before);self.assertIn('附件价格',d.error.text())

    def test_single_row_editing_and_zero_discount_keep_locked_amounts(self):
        d = self.dialog();self.apply(d,.5)
        d.grid.item(1,2).setText('600.01')
        self.assertEqual(ui._row_values(d.items[1])[15],600.01)
        self.assertEqual(ui._row_values(d.items[0])[15],620)
        self.apply(d,0)
        self.assertEqual([ui._row_values(i)[15] for i in d.items],[60,60,400])
        self.assertEqual(d.items[0]['attachments'][1]['quick_amount'],50)
        self.assertEqual(d.items[0]['freight_fee'],10)
        self.assertEqual(d.grid.item(0,4).text(),'0.9')

    def test_attachment_editor_refreshes_and_manual_eligible_price_survives_batch(self):
        d = self.dialog(); d.show(); APP.processEvents()
        d.attachment_row(0); grid=d.attachment_panel.findChild(QTableWidget)
        self.assertTrue(grid.cellWidget(1,2).isReadOnly())
        d.change_attachment(0,0,'100',grid)
        self.apply(d,.5)
        self.assertTrue(d.attachment_panel.isHidden())
        d.attachment_row(0); grid=d.attachment_panel.findChildren(QTableWidget)[-1]
        self.assertEqual(grid.item(0,4).text(),'50.00')
        self.assertEqual(grid.item(1,4).text(),'50.00')
        self.assertEqual(ui._row_values(d.items[0])[15],610)
        self.assertEqual(d.items[0]['attachments'][0]['unit_price_override'],100)
        self.assertEqual(d.items[0]['attachments'][0]['formula_amount'],50)
        self.assertEqual(d.items[0]['attachments'][1]['quick_amount'],50)
        d.reject()

    def test_review_back_cancel_and_reason_validation(self):
        source=batch_items();d=self.dialog(source);self.apply(d,.5)
        d.accept();self.assertFalse(d.reviewing);self.assertIn('调价原因',d.error.text())
        d.reason.setPlainText('合成批量调价');d.accept()
        self.assertTrue(d.reviewing);self.assertTrue(d.batch_panel.isHidden())
        before=deepcopy(d.items);self.apply(d,.3);self.assertEqual(d.items,before)
        d.back();self.assertFalse(d.batch_panel.isHidden())
        self.assertEqual(d.inputs[0,5].text(),'0.5')
        d.reject();self.assertEqual(d._result,QDialog.DialogCode.Rejected)
        self.assertEqual(source,batch_items())
        empty=self.dialog([])
        self.assertFalse(empty.batch_apply.isEnabled())
        self.assertEqual(empty.batch_scope.text(),'暂无产品')

    def test_keyboard_apply_and_real_window_layout(self):
        d=self.dialog()
        self.m.root.addWidget(d);d.setWindowFlags(Qt.WindowType.Widget);self.m.root.setCurrentWidget(d)
        self.addCleanup(lambda:self.m.root.setCurrentWidget(self.m.detail_page))
        d.show();APP.processEvents()
        d.batch_factor.setFocus();d.batch_factor.selectAll();QTest.keyClicks(d.batch_factor,'0.45')
        QTest.keyClick(d.batch_factor,Qt.Key.Key_Return);APP.processEvents()
        self.assertEqual([i['quick_discount'] for i in d.items],[.45,.45,.8])
        output=Path(os.environ.get('AI_QUOTE_BATCH_SCREENSHOT_DIR',str(fixture.ROOT/'outputs'/'quote-batch-discount')))
        output.mkdir(parents=True,exist_ok=True)
        for width,height in ((1510,960),(1024,768)):
            self.w.resize(width,height);APP.processEvents();QTest.qWait(50)
            for control in (d.batch_product,d.batch_factor,d.batch_apply,d.primary,d.cancel_button):
                self.assertTrue(control.isVisibleTo(self.w))
                self.assertTrue(self.w.rect().contains(control.mapTo(self.w,control.rect().bottomRight())))
            self.assertLess(d.batch_product.mapTo(d,d.batch_product.rect().topRight()).x(),
                            d.batch_factor.mapTo(d,d.batch_factor.rect().topLeft()).x())
            self.assertEqual(d.batch_apply.height(),LIGHT_ACTION['height'])
            self.assertEqual(d.grid.horizontalScrollBar().maximum(),0)
            self.assertTrue(self.w.grab().save(str(output/f'batch-{width}-{os.environ.get("QT_SCALE_FACTOR","1")}.png')))
        d.reason.setPlainText('合成视觉验证');d.accept();APP.processEvents()
        self.assertTrue(d.batch_panel.isHidden())
        self.assertTrue(self.w.grab().save(str(output/f'review-{os.environ.get("QT_SCALE_FACTOR","1")}.png')))
        d.reject()

    def test_confirmation_saves_each_version_reopens_and_exports_real_workbook(self):
        self.w._quote_scheme_loading=True
        self.w.draft_items=batch_items();self.w._qm_state=model.restore_state(None)
        self.m.generated();self.w.refresh_summary();self.w._quote_scheme_loading=False
        self.w._quote_scheme_save_timer.stop()
        prior=deepcopy(self.m.state['versions'])
        for number,value in ((2,.5),(3,.4),(4,.6)):
            errors=[]
            def confirm():
                d=self.m.root.currentWidget()
                try:
                    self.assertIsInstance(d,qm.AdjustQuoteDialog)
                    request_count=len(self.requests)
                    self.apply(d,value)
                    self.assertEqual(len(self.requests),request_count)
                    self.assertEqual(self.m.state['versions'],prior)
                    d.reason.setPlainText(f'合成第{number}版批量调价');d.accept()
                    self.assertTrue(d.reviewing)
                    self.assertEqual(self.m.state['versions'],prior)
                    d.accept()
                except Exception as error:
                    errors.append(error);d.reject()
            QTimer.singleShot(0,confirm);self.m.adjust()
            self.assertFalse(errors,errors)
            fixture.wait(lambda:not self.w._quote_scheme_workers)
            self.w._quote_scheme_save_timer.stop()
            self.assertEqual(self.m.state['versions'][:-1],prior)
            self.assertEqual(self.m.state['current'],number)
            self.assertTrue(self.m.state['versions'][-1]['confirmed'])
            self.assertEqual(self.saved['quote_management']['current'],number)
            prior=deepcopy(self.m.state['versions'])
        saved=deepcopy(self.saved)
        fixture.centre._apply_opened_scheme(self.w,dict(scheme_no=self.w._quote_scheme_id,status='DRAFT',
            lock_version=self.w._quote_scheme_version,version_no=1,snapshot=saved,
            quote_management_historical_export=True),2)
        self.w._quote_scheme_save_timer.stop()
        self.assertEqual(self.m.history.rowCount(),4)
        self.assertEqual([ui._row_values(i)[15] for i in self.w.draft_items],[732,612,400])
        self.assertIn('2,196.00',ui._printable_quote_html(self.w))
        self.assertIn('3,608.00',ui._printable_quote_html(self.w))
        from verify_quote_export_customer import workbook_cell
        with tempfile.TemporaryDirectory(prefix='batch-discount-export-') as folder:
            source,output=Path(folder)/'synthetic.json',Path(folder)/'synthetic.xlsx'
            source.write_text(json.dumps(dict(items=ui._quote_export_items_snapshot(self.w),
                company_name='合成批量调价客户',quote_date='2026-10-27'),ensure_ascii=False),encoding='utf-8')
            result=subprocess.run(['node',str(fixture.ROOT/'export_dual_quote_workbook.mjs'),str(source),str(output)],
                cwd=fixture.ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(float(workbook_cell(output,'报价','F11')),732)
            self.assertEqual(float(workbook_cell(output,'报价','G11')),2196)
            self.assertEqual(float(workbook_cell(output,'报价','F12')),612)
            self.assertEqual(float(workbook_cell(output,'报价','G12')),612)


if __name__=='__main__':unittest.main()
