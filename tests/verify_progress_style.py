"""Render real client progress fills, including failures and new dialogs."""
import os
from pathlib import Path
import unittest

import verify_quote_document_progress as base
from PySide6.QtWidgets import QDialog, QProgressBar, QProgressDialog, QVBoxLayout
from PySide6.QtTest import QTest
import scheme2_ui as ui
from progress_style import PROGRESS_COLORS, install_progress_style


class GreenProgress(unittest.TestCase):
    setUp = base.DocumentProgress.setUp

    def settle(self):
        base.app.processEvents()
        QTest.qWait(10)

    def assert_green(self, bar):
        if bar.maximum() <= bar.minimum():
            bar.setRange(0, 100)
        bar.setValue(bar.minimum() + max(1, (bar.maximum() - bar.minimum()) // 2))
        bar.resize(300, 20)
        bar.ensurePolished()
        self.settle()
        image = bar.grab().toImage()
        # Native dialogs may place text over any particular sample pixel.
        # Check the filled region rather than mistaking antialiased glyphs
        # or rounded ends for the progress colour.
        fill = PROGRESS_COLORS['fill'].upper()
        green_pixels = sum(image.pixelColor(x, y).name().upper() == fill
                           for y in range(image.height()) for x in range(image.width()))
        self.assertGreater(green_pixels, image.width() * image.height() * .05, bar.objectName())

    def test_add_running_paused_failed_and_complete_use_same_green(self):
        w = self.window
        w.show_section(ui.OPTION_ROUTE)
        w.show()
        for label, failed, paused in (('计算中', False, False), ('已暂停', False, True),
                                       ('失败：测试原因', True, False), ('已完成', False, False)):
            with self.subTest(label=label):
                ui._set_add_progress(w, 3, label, failed=failed)
                w.scheme2_add_progress.setProperty('paused', paused)
                self.assert_green(w.scheme2_add_progress)
                self.assertEqual(w.scheme2_add_progress.property('failed'), failed)
                if failed:
                    self.assertEqual(w.scheme2_add_progress.property('failureReason'), '测试原因')
        capture = os.environ.get('AI_QUOTE_UI_ARTIFACT_DIR')
        if capture:
            folder = Path(capture)
            folder.mkdir(parents=True, exist_ok=True)
            w.scheme2_add_progress.grab().save(str(folder / 'add-progress-green.png'))

    def test_generate_and_export_track_share_green(self):
        c = self.controller
        self.window.show()
        for kind, route in (('generate', ui.COST_ROUTE), ('export', ui.QUOTE_ROUTE)):
            with self.subTest(kind=kind):
                if route == ui.QUOTE_ROUTE: self.window._qm_entry_pending = True
                self.window.show_section(route)
                c.begin(kind)
                c._show_busy()
                bar = c.widgets[kind][1]
                self.assert_green(bar)
                capture = os.environ.get('AI_QUOTE_UI_ARTIFACT_DIR')
                if capture:
                    folder = Path(capture)
                    folder.mkdir(parents=True, exist_ok=True)
                    c.widgets[kind][0].grab().save(str(folder / f'{kind}-progress-green.png'))
                c.end(cancelled=True)

    def test_all_existing_bars_and_dynamic_dialogs_use_green(self):
        w = self.window
        w.show()
        bars = w.findChildren(QProgressBar)
        self.assertGreaterEqual(len(bars), 4)
        for bar in bars:
            with self.subTest(name=bar.objectName()):
                if bar.objectName() == 'drawingProgress':
                    # This retired controller is intentionally zero-height in
                    # the live UI. Expose its actual paint surface in the
                    # current window rather than the zero-size retired host.
                    bar.setParent(w)
                    bar.setStyleSheet('QProgressBar#drawingProgress { min-height:20px; max-height:20px; }')
                    bar.show()
                self.assert_green(bar)
        dialog = QDialog(w)
        layout = QVBoxLayout(dialog)
        dynamic = QProgressBar(dialog)
        layout.addWidget(dynamic)
        dialog.show()
        self.assert_green(dynamic)
        dynamic.setEnabled(False)
        self.assert_green(dynamic)
        dialog.close()
        native = QProgressDialog('测试进度', '取消', 0, 100, w)
        native.setAutoClose(False)
        native.setMinimumDuration(0)
        native.setValue(50)
        native.show()
        self.assert_green(native.findChild(QProgressBar))
        native.close()

    def test_installer_is_idempotent_and_window_rescaling_keeps_green(self):
        before = base.app.styleSheet()
        install_progress_style()
        install_progress_style()
        self.assertEqual(base.app.styleSheet(), before)
        self.window.show()
        for width in (1024, 1550, 1200):
            self.window.resize(width, 850)
            ui._set_add_progress(self.window, 3, '处理中')
            self.assert_green(self.window.scheme2_add_progress)


if __name__ == '__main__':
    unittest.main(verbosity=2)
