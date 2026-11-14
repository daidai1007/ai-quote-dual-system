"""Actual Qt events for editing the attachment's pre-discount unit price."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox, QWidget
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
        self.amount = self.dialog.table.cellWidget(0, self.dialog.COL_UNIT_AMOUNT)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.dialog.close)

    def click_price(self, row, *, double=True):
        table = self.dialog.table
        price = table.item(row, self.dialog.COL_DISCOUNTED_UNIT)
        table.scrollToItem(price)
        pos = table.visualItemRect(price).center()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        if double:
            QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    def edit_price(self, row, value, *, confirm=True):
        def edit(dialog):
            amount = dialog.findChild(QDoubleSpinBox)
            amount.lineEdit().selectAll()
            QTest.keyClicks(amount.lineEdit(), value)
            buttons = dialog.findChild(QDialogButtonBox)
            button = QDialogButtonBox.StandardButton.Ok if confirm else QDialogButtonBox.StandardButton.Cancel
            buttons.button(button).click()
            return dialog.result()
        with patch.object(QDialog, 'exec', edit):
            self.click_price(row)

    def test_single_click_keeps_display_double_click_opens_price_editor(self):
        with patch.object(QDialog, 'exec') as popup:
            self.click_price(0, double=False)
            popup.assert_not_called()
        self.edit_price(0, '210')
        self.assertEqual(self.amount.value(), 210)
        self.dialog.accept()
        row = self.item['attachments'][0]
        self.assertEqual(row['quick_amount_override'], 420)
        self.assertEqual(row['formula_amount'], 62.96)
        reopened = ui.AttachmentEditor(self.owner, self.item)
        self.addCleanup(reopened.close)
        self.assertEqual(float(reopened.table.item(0, reopened.COL_AMOUNT).text().replace(",", "")), 420)

    def test_cancel_keeps_price_and_confirm_saves_manual_zero(self):
        self.edit_price(0, '0', confirm=False)
        self.assertEqual(self.amount.value(), 60)
        self.edit_price(0, '0')
        self.dialog.accept()
        self.assertEqual(self.item['attachments'][0]['quick_amount_override'], 0)
        self.assertTrue(self.item['attachments'][0]['custom_amount_edited'])

    def test_pending_dimensions_cannot_open_edit_box(self):
        source = dict(item_name='玻璃门', attachment_price_id=102, quantity=1,
                      pending_manual_dimensions=['玻璃门高度'], status='PENDING_MANUAL')
        self.dialog.add_row(source)
        pending = self.dialog.table.cellWidget(1, self.dialog.COL_UNIT_AMOUNT)
        with patch.object(QDialog, 'exec') as popup:
            self.click_price(1)
            popup.assert_not_called()
        self.assertFalse(pending.isEnabled())

    def test_custom_cost_link_survives_amount_edit_box(self):
        self.dialog.add_row(dict(custom=True,item_name='临时附件',quantity=1,formula_amount=10,quick_amount=12))
        cost = self.dialog.table.cellWidget(1, self.dialog.COL_UNIT_COST)
        amount = self.dialog.table.cellWidget(1, self.dialog.COL_UNIT_AMOUNT)
        cost.setValue(60)
        self.assertEqual(amount.value(),72)
        self.edit_price(1, '90')
        cost.setValue(75)
        self.assertEqual(amount.value(),90)


if __name__ == '__main__':
    unittest.main()
