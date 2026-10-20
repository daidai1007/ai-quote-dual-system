"""Light, taller attachment actions and an opaque white footer; no network."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFrame, QLabel,
                              QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)
import scheme2_ui as ui
from dialog_style import DIALOG_COLORS, install_dialog_style, style_dialog

app = QApplication.instance() or QApplication([])
app.setStyle('Fusion')
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families = QFontDatabase.applicationFontFamilies(font_id)
if families:
    app.setFont(QFont(families[0],10))
install_dialog_style()


class LegacyPicker(QDialog):
    def __init__(self, selected, **kwargs):
        super().__init__(kwargs['parent'])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('附件价格清单'))
        layout.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def collect_attachments(self):
        return []


class AttachmentAddStyle(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.resize(600, 650)
        # Reproduce the recovered client's inherited filled button rule.
        self.owner.setStyleSheet('QPushButton {background:#2165A6;max-height:26px;min-height:26px;}')
        self.owner.attachments = []
        self.owner.base_url = lambda: 'http://offline.invalid'
        for name in ('width_spin','height_spin','depth_spin'):
            setattr(self.owner,name,SimpleNamespace(value=lambda:300))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.reject()
        self.owner.close()
        app.processEvents()

    def picker(self):
        dialog=ui._SchemeAttachmentDialog([], 'JA', self.owner)
        self.dialogs.append(dialog)
        dialog.resize(400,500)
        dialog.show()
        app.processEvents()
        frame=dialog.findChild(QFrame,'scheme2CustomAttachmentCard')
        dialog.findChild(QScrollArea).ensureWidgetVisible(frame)
        app.processEvents()
        return dialog

    def assert_actions(self, dialog):
        button=dialog.findChild(QPushButton,'scheme2AddAttachment')
        self.assertEqual(button.height(),ui.ATTACHMENT_ADD_METRICS['button_height'])
        frame=dialog.findChild(QFrame,'scheme2CustomAttachmentCard')
        self.assertGreaterEqual(frame.height(),60)
        self.assertIn(DIALOG_COLORS['selected'],button.styleSheet())
        image=button.grab().toImage()
        self.assertEqual(image.pixelColor(12,image.height()//2).name(),DIALOG_COLORS['selected'].lower())
        # Previously a transparent frameless dialog exposed a black strip here.
        image=dialog.grab().toImage()
        self.assertEqual(image.pixelColor(5,image.height()-5).name(),DIALOG_COLORS['background'].lower())
        box=dialog.findChild(QDialogButtonBox)
        for action in box.buttons():
            self.assertTrue(action.isVisible())
            bottom=action.mapTo(dialog,action.rect().bottomRight())
            self.assertLess(bottom.y(),dialog.height())
        return button

    def test_current_picker_light_tall_add_and_unchanged_confirm(self):
        dialog=self.picker()
        add=self.assert_actions(dialog)
        original=dialog.styleSheet()
        style_dialog(dialog)
        self.assertEqual(dialog.styleSheet(),original)
        add.click()
        name=dialog.findChild(QLineEdit,'scheme2CustomAttachmentName')
        name.setText('手工附件')
        dialog.findChild(QPushButton,'scheme2CustomAttachmentConfirm').click()
        self.assertEqual(dialog.collect_attachments()[-1]['item_name'],'手工附件')
        self.assertEqual(add.height(),44)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        self.assertEqual(dialog.result(),QDialog.Accepted)

    def test_footer_white_at_small_and_tall_sizes_and_cancel(self):
        dialog=self.picker()
        for height in (320,650):
            dialog.resize(400,height)
            app.processEvents()
            self.assert_actions(dialog)
        out=ROOT/'outputs'/('attachment-add-style-'+os.environ.get('QT_SCALE_FACTOR','1'))
        out.mkdir(parents=True,exist_ok=True)
        dialog.findChild(QScrollArea).ensureWidgetVisible(dialog.findChild(QFrame,'scheme2CustomAttachmentCard'))
        app.processEvents()
        self.assertTrue(dialog.grab().save(str(out/'picker.png')))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).click()
        self.assertEqual(dialog.result(),QDialog.Rejected)

    def test_legacy_overlay_uses_same_light_tall_row_and_white_footer(self):
        anchor=QWidget(self.owner)
        anchor.resize(400,500)
        ui._open_legacy_attachment_overlay(self.owner,LegacyPicker,anchor)
        dialog=self.owner._scheme2_attachment_overlay
        self.dialogs.append(dialog)
        app.processEvents()
        add=self.assert_actions(dialog)
        add.click()
        self.assertFalse(add.isVisible())
        dialog.reject()
        self.assertEqual(self.owner.attachments,[])


if __name__ == '__main__':
    unittest.main()
