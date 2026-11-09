"""Exercise page orientation in the real PDF preview without invoking OCR."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from pypdf import PdfReader, PdfWriter
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from drawing_orientation import pdf_view_rotation
from quote_drawing_preview import QuoteDrawingPreview
from verify_native_dimension_lines import diagram


class DrawingOrientationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "drawing.pdf"
        diagram(self.source)

    def test_metadata_and_baked_rotation_are_measured_relative_to_preview(self):
        with PdfReader(self.source) as reader, PdfWriter() as writer:
            page = writer.add_page(reader.pages[0])
            self.assertEqual(pdf_view_rotation(page), 0)
            for angle in (90, 180, 270):
                page.rotation = angle
                self.assertEqual(pdf_view_rotation(page), (-angle) % 360)
                page.transfer_rotation_to_content()
                self.assertEqual(page.rotation, 0)
                self.assertEqual(pdf_view_rotation(page), (-angle) % 360)
                page.rotate(-angle)
                page.transfer_rotation_to_content()

    def test_numeric_labels_alone_do_not_determine_upright(self):
        diagram(self.source, captions=False, units="")
        with PdfReader(self.source) as reader:
            self.assertIsNone(pdf_view_rotation(reader.pages[0]))

    def test_hidden_text_layer_does_not_override_visible_scan(self):
        diagram(self.source, hidden=True)
        with PdfReader(self.source) as reader:
            self.assertIsNone(pdf_view_rotation(reader.pages[0]))

    def test_first_preview_of_selected_page_and_manual_rotation_survive_cache(self):
        app = QApplication.instance() or QApplication([])
        renderer = Path(os.environ["AI_QUOTE_V3_CORE_ROOT"]).parents[1] / "runtime/poppler/bin/pdftoppm.exe"
        self.assertTrue(renderer.is_file(), renderer)
        with PdfReader(self.source) as reader, PdfWriter() as writer:
            writer.add_page(reader.pages[0])
            writer.reset_translation(reader)
            page = writer.add_page(reader.pages[0])
            page.rotate(90)
            page.transfer_rotation_to_content()
            writer.write(self.root / "two-pages.pdf")
        path = self.root / "two-pages.pdf"
        original = hashlib.sha256(path.read_bytes()).digest()
        fallback_calls = []
        preview = QuoteDrawingPreview(str(renderer), None,
            orientation_probe=lambda *_: fallback_calls.append(True))

        def wait_ready():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                app.processEvents()
                if preview.canvas.isEnabled() and not preview._workers:
                    return
                QTest.qWait(10)
            self.fail(preview.message.text())

        try:
            preview.set_document("page-2", str(path), str(path), page_index=1)
            self.assertEqual(len(preview._workers), 1)
            wait_ready()
            self.assertEqual((preview.page, preview.canvas.rotation_degrees), (1, 270))
            preview.rotate_button.click()
            self.assertEqual(preview.canvas.rotation_degrees, 0)
            preview.set_document("page-1", str(path), str(path), page_index=0)
            wait_ready()
            self.assertEqual((preview.page, preview.canvas.rotation_degrees), (0, 0))
            preview.set_document("page-2", str(path), str(path), page_index=1)
            wait_ready()
            self.assertEqual((preview.page, preview.canvas.rotation_degrees), (1, 0))
            self.assertFalse(fallback_calls)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), original)
        finally:
            for worker in tuple(preview._workers):
                worker.requestInterruption()
                worker.wait()
            preview.close()

    def test_raster_probe_rotation_is_applied_to_first_frame(self):
        app = QApplication.instance() or QApplication([])
        path = self.root / "scan.png"
        image = QImage(300, 400, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        self.assertTrue(image.save(str(path)))
        calls = []

        def probe(frame, cancelled):
            calls.append((frame.width(), frame.height()))
            return 90

        preview = QuoteDrawingPreview(None, None, orientation_probe=probe)
        try:
            preview.set_document("scan", str(path), str(path))
            worker = next(iter(preview._workers))
            self.assertTrue(worker.wait(5000))
            app.processEvents()
            self.assertTrue(preview.canvas.isEnabled())
            self.assertEqual(preview.canvas.rotation_degrees, 90)
            self.assertEqual(calls, [(300, 400)])
            path.unlink()  # The image reader releases the source before OCR/preview.
        finally:
            for worker in tuple(preview._workers):
                worker.requestInterruption()
                worker.wait()
            preview.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
