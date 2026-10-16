"""Actual Qt events for the selected-attachment amount's inline editing box."""
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import scheme2_ui as ui

app = QApplication.instance() or QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
font_families = QFontDatabase.applicationFontFamilies(font_id)
if font_families:
    app.setFont(QFont(font_families[0],9))


class AmountDoubleClick(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.refresh_summary = lambda: None
        self.item = dict(quantity=3, attachments=[dict(item_name='并柜件', attachment_price_id=101,
            quantity=2, quick_amount=120, formula_amount=62.96, matched_price=60)],
            quick={'attachment_fee':120,'total_cost':1120}, formula={'attachment_fee':62.96,'total_cost':562.96})
        self.dialog = ui.AttachmentEditor(self.owner, self.item)
        self.dialog.show()
        app.processEvents()
        self.amount = self.dialog.table.cellWidget(0, self.dialog.COL_AMOUNT)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.dialog.close)

    def begin_edit(self):
        QTest.mouseDClick(self.amount.lineEdit(), Qt.MouseButton.LeftButton)
        app.processEvents()

    def test_single_click_keeps_display_double_click_shows_edit_box_and_enter_saves(self):
        line = self.amount.lineEdit()
        QTest.mouseClick(line, Qt.MouseButton.LeftButton)
        QTest.keyClicks(line, '99')
        self.assertTrue(line.isReadOnly())
        self.assertFalse(self.amount.property('schemeEditing'))
        self.assertEqual(self.amount.value(), 120)
        self.begin_edit()
        self.assertFalse(line.isReadOnly())
        self.assertTrue(self.amount.property('schemeEditing'))
        self.assertEqual(line.selectedText(), line.text())
        self.assertIn('[schemeEditing="true"]', self.dialog.styleSheet())
        self.assertTrue(self.dialog.grab().save(str(ROOT/'outputs/attachment-amount-double-click.png')))
        QTest.keyClicks(line, '210')
        QTest.keyClick(line, Qt.Key.Key_Return)
        app.processEvents()
        self.assertTrue(line.isReadOnly())
        self.assertFalse(self.amount.property('schemeEditing'))
        self.assertEqual(self.amount.value(), 210)
        self.dialog.accept()
        row = self.item['attachments'][0]
        self.assertEqual(row['quick_amount_override'], 210)
        self.assertEqual(row['formula_amount'], 62.96)
        reopened = ui.AttachmentEditor(self.owner, self.item)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.table.cellWidget(0,reopened.COL_AMOUNT).value(), 210)

    def test_focus_out_hides_edit_box_and_keeps_manual_zero(self):
        self.begin_edit()
        QTest.keyClicks(self.amount.lineEdit(), '0')
        quantity = self.dialog.table.cellWidget(0,self.dialog.COL_QUANTITY)
        QTest.mouseClick(quantity, Qt.MouseButton.LeftButton)
        app.processEvents()
        self.assertTrue(self.amount.lineEdit().isReadOnly())
        self.assertFalse(self.amount.property('schemeEditing'))
        self.dialog.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount_override'], 0)
        self.assertTrue(self.item['attachments'][0]['custom_amount_edited'])

    def test_pending_dimensions_cannot_open_edit_box(self):
        source = dict(item_name='玻璃门', attachment_price_id=102, quantity=1,
                      pending_manual_dimensions=['玻璃门高度'], status='PENDING_MANUAL')
        self.dialog.add_row(source)
        pending = self.dialog.table.cellWidget(1,self.dialog.COL_AMOUNT)
        QTest.mouseDClick(pending.lineEdit(),Qt.MouseButton.LeftButton)
        self.assertFalse(pending.isEnabled())
        self.assertTrue(pending.lineEdit().isReadOnly())
        self.assertFalse(pending.property('schemeEditing'))

    def test_custom_cost_link_survives_amount_edit_box(self):
        self.dialog.add_row(dict(custom=True,item_name='临时附件',quantity=1,formula_amount=10,quick_amount=12))
        cost = self.dialog.table.cellWidget(1,self.dialog.COL_FORMULA_AMOUNT)
        amount = self.dialog.table.cellWidget(1,self.dialog.COL_AMOUNT)
        cost.setValue(60)
        self.assertEqual(amount.value(),72)
        QTest.mouseDClick(amount.lineEdit(),Qt.MouseButton.LeftButton)
        self.assertTrue(amount.property('schemeEditing'))
        QTest.keyClicks(amount.lineEdit(),'90')
        QTest.keyClick(amount.lineEdit(),Qt.Key.Key_Return)
        cost.setValue(75)
        self.assertEqual(amount.value(),90)
        self.assertTrue(amount.lineEdit().isReadOnly())


if __name__ == '__main__':
    unittest.main()
