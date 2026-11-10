"""Regressions for the shared page scan and the existing quote evidence gate."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from quote_drawing_preview import QuoteDrawingPreview
from recognition_first_pass import (
    PageScan, _oriented_reading, _printed_sizes, install_first_pass, page_scan_scope,
    refine_pending_size_evidence,
)


def reading(horizontal=True):
    box = [(10, 10), (190, 10), (190, 30), (10, 30)]
    if not horizontal:
        box = [(y, x) for x, y in box]
    text = ["表面处理和技术要求", "图号柜体设计审核", "柜体整体安装接地说明"]
    return SimpleNamespace(boxes=[box] * len(text), txts=text, scores=[.98] * len(text))


class FirstPassTests(unittest.TestCase):
    def setUp(self):
        self.image = QImage(300, 400, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)

    def test_confident_upright_page_runs_one_read(self):
        calls = []

        def read(data, _cancelled):
            calls.append(data)
            return reading()

        self.assertEqual(_oriented_reading(self.image, read, None)[0], 0)
        self.assertEqual(len(calls), 1)

    def test_sideways_page_tries_another_angle_only_after_weak_first_read(self):
        outputs = iter((reading(False), reading()))
        self.assertEqual(_oriented_reading(self.image, lambda *_: next(outputs), None)[0], 270)
        self.assertIsNone(next(outputs, None))

    def test_independent_review_reuses_first_reading_and_orientation(self):
        calls = []
        contract = {
            "RAPIDOCR_ENGINE_NAME": "rapid",
            "OCRToken": lambda text, confidence, x, y, orientation, polygon: SimpleNamespace(
                text=text, confidence=confidence, center_x=x, center_y=y, orientation=orientation, polygon=polygon),
            "_polygon_text_orientation": lambda _: "horizontal",
            "OCRReading": lambda engine, angle, text, confidence, count, tokens, w, h: SimpleNamespace(
                engine=engine, angle=angle, text=text, mean_confidence=confidence,
                tokens=tokens, audit_dict=lambda: {"text": text}),
        }

        class Core:
            @staticmethod
            def _dual_ocr_page(path, angles):
                reads, error = namespace["rapidocr_angle_readings"](path, angles)
                calls.append(("review", angles, reads[0].text))
                return {"ocr_engine_evidence": {}, "has_red": False}

            @staticmethod
            def _refresh_ocr_consensus(details):
                details["ocr_engine_evidence"]["rapid"]["specification_candidates"] = [
                    {"specification": "800*600*1800"}
                ]
                return details

            @staticmethod
            def extract_technical_requirements(text):
                return "\n".join(f"{index}.要求" for index in range(1, 6))

            @staticmethod
            def _ocr_numbered_requirements_region(path):
                return ""

            @staticmethod
            def _infer_dimensions_from_views(path):
                return None

        def read(*args):
            calls.append("read")
            return reading()

        def repeat(*args):
            self.fail("Independent verification started RapidOCR again")

        namespace = dict(DrawingRecognitionTools=Core, _read_local_ocr_for_orientation=read,
                         _rapidocr_reading_contract=contract, rapidocr_angle_readings=repeat)
        install_first_pass(namespace)
        with tempfile.TemporaryDirectory() as folder:
            source = str(Path(folder) / "page.png")
            self.assertTrue(self.image.save(source))
            scan = PageScan()
            scan.publish(270)
            with page_scan_scope(scan):
                result = Core._dual_ocr_page(source)
            self.assertEqual(result["source_page_rotation"], 270)
            self.assertEqual(scan.primary_reads, 1)
            self.assertEqual(calls[0], "read")
            self.assertEqual(calls[1][:2], ("review", (0,)))
            self.assertEqual(len(calls), 2)

            calls.clear()
            corroborated = PageScan()
            corroborated.native_rotation = 0
            corroborated.native_text = "柜体宽800 mm\n柜体深600 mm\n本体高1800 mm"
            corroborated.publish(0)
            with page_scan_scope(corroborated):
                result = Core._dual_ocr_page(source)
            self.assertEqual(calls, ["read"])
            self.assertEqual(corroborated.mode, "first_pass")
            self.assertEqual(result["recognition_engines"], ["rapid"])

    def test_title_candidate_does_not_confirm_or_reuse_local_partial(self):
        def token(text, *, x=.72, y=.82, confidence=.95):
            return SimpleNamespace(text=text, center_x=x, center_y=y, confidence=confidence, orientation="horizontal")

        self.assertEqual(_printed_sizes([token("L950×H2100×W500")]), {"950*500*2100"})
        self.assertFalse(_printed_sizes([token("L950×H2100×W500", y=.2)]))
        self.assertFalse(_printed_sizes([token("L950×H2100×W500-550")]))
        self.assertFalse(_printed_sizes([token("1.尺寸:宽600*高2000+200*1000深")]))
        self.assertEqual(_printed_sizes([token("1.尺寸:宽600*高2000+200*1000深"), token("配200mm高黑色底座")]),
                         {"600*1000*(2000+200)"})
        record = dict(specification="", dimensions=[], ocr_confirmation_required=True, dimension_review_required=True,
                      dimension_recognition={"status": "partial", "partial": {"W": 130, "D": 238}})
        refine_pending_size_evidence(record, "", ("950*500*2100",))
        self.assertEqual(record["dimension_recognition"]["partial"], {})
        self.assertEqual(record["dimension_recognition"]["review_display_specification"], "950*500*2100")
        self.assertEqual(record["dimensions"], [])
        self.assertTrue(record["dimension_review_required"])
        self.assertTrue(record["ocr_confirmation_required"])
        self.assertTrue(record["dimension_recognition"]["candidates"][0]["review_only"])
        conflicting = tuple(sorted(_printed_sizes([
            token("600*600*210(宽*高深)"), token("1.尺寸:宽600*高660*深210"),
        ])))
        self.assertEqual(conflicting, ("600*210*600", "600*210*660"))
        record.update(specification="600*210*660", dimensions=[(600, 660, 210)], dimension_review_required=False,
                      dimension_recognition={"status": "recognized", "partial": {}})
        refine_pending_size_evidence(record, "", conflicting)
        self.assertEqual(record["dimension_recognition"]["status"], "conflict")
        self.assertNotIn("review_display_specification", record["dimension_recognition"])
        self.assertEqual(record["dimensions"], [])
        self.assertTrue(record["dimension_review_required"])

    def test_preview_uses_worker_rotation_without_its_own_ocr(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            source = str(Path(folder) / "page.png")
            self.assertTrue(self.image.save(source))
            scan = PageScan()
            called = []
            preview = QuoteDrawingPreview(None, None, orientation_probe=lambda *_: called.append(True))
            try:
                preview.set_document("key", source, source, page_scan=scan)
                worker = next(iter(preview._workers))
                scan.publish(270)
                self.assertTrue(worker.wait(5000))
                app.processEvents()
                self.assertEqual(preview.canvas.rotation_degrees, 270)
                self.assertFalse(called)
            finally:
                for worker in tuple(preview._workers):
                    worker.requestInterruption()
                    worker.wait()
                preview.close()

    def test_outer_dimension_lines_take_precedence_over_conflicting_prose(self):
        from native_dimension_lines import inspect_single_page_pdf
        from verify_native_dimension_lines import diagram

        with tempfile.TemporaryDirectory() as folder:
            source = str(Path(folder) / "drawing.pdf")
            diagram(source)
            lines = inspect_single_page_pdf(source)["dimension_lines"]
        self.assertEqual(lines["specification"], "800*600*1800")
        self.assertEqual(lines["units"], "mm")
        record = dict(specification="800*600*1860", dimensions=[(800, 1860, 600)],
                      dimension_review_required=False, native_dimension_lines=lines,
                      dimension_recognition={"status": "recognized", "candidates": [
                          {"specification": "800*600*1860"},
                      ]})
        refine_pending_size_evidence(record, "", ("800*600*1860",))
        self.assertTrue(record["dimension_review_required"])
        self.assertEqual(record["dimensions"], [])
        self.assertEqual(record["dimension_recognition"]["review_display_specification"], "800*600*1800")
        self.assertEqual(record["dimension_recognition"]["status"], "conflict")

        # A dimension line can mark total height while a valid expression
        # separately records the body and the base.
        record.update(specification="800*600*(1700+100)", dimensions=[(800, 1700, 600)],
                      dimension_review_required=False)
        refine_pending_size_evidence(record, "", ())
        self.assertEqual(record["dimensions"], [(800, 1700, 600)])
        self.assertFalse(record["dimension_review_required"])

    def test_failure_releases_preview_waiter(self):
        scan = PageScan()
        with self.assertRaises(ValueError):
            with page_scan_scope(scan):
                raise ValueError("test page failed")
        self.assertTrue(scan.ready.is_set())
        self.assertIsNone(scan.wait_rotation(lambda: False))

    def test_edocr2_outline_prefers_600_over_prose_and_preserves_confirmation(self):
        record = dict(specification="600*210*660", dimensions=[(600, 660, 210)],
                      dimension_review_required=False, dimension_recognition={"candidates": []})
        outline = dict(status="candidate", specification="600*210*600",
                       partial={"W": 600, "D": 210, "H": 600})
        refine_pending_size_evidence(record, "", ("600*210*660",), outline)
        self.assertEqual(record["dimension_recognition"]["review_display_specification"], "600*210*600")
        self.assertEqual(record["dimension_recognition"]["status"], "conflict")
        self.assertEqual(record["dimensions"], [])
        self.assertTrue(record["dimension_review_required"])

    def test_edocr2_overall_height_keeps_an_explicit_base_split(self):
        token = lambda text: SimpleNamespace(text=text, center_x=.16, center_y=.78,
                                              confidence=.99, orientation="horizontal")
        spec = _printed_sizes([token("600*高2000+200*1000深"), token("配200mm高黑色底座")])
        self.assertEqual(spec, {"600*1000*(2000+200)"})
        self.assertFalse(_printed_sizes([token("600*高2000+200*1000深")]))
        record = dict(specification="", dimensions=[], dimension_review_required=True,
                      dimension_recognition={"candidates": []})
        outline = dict(status="candidate", specification="600*1000*2200",
                       partial={"W": 600, "D": 1000, "H": 2200})
        refine_pending_size_evidence(record, "", tuple(spec), outline)
        self.assertEqual(record["dimension_recognition"]["review_display_specification"], "600*1000*(2000+200)")
        self.assertTrue(record["dimension_review_required"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
