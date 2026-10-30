"""Current-core Qt regressions, offline; never run drawing recognition."""
from copy import deepcopy
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))


def no_network(*_args, **_kwargs):
    raise AssertionError("network is disabled for dimension UI tests")


socket.create_connection = no_network
socket.socket.connect = no_network

from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
import scheme2_ui as ui
import v3_launcher
import client_update_ui
from recognition_dimensions import reconcile_recognition_dimensions
from recognition_repair import repair_recognition_result

app = QApplication.instance() or QApplication([])
for font_name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisym.ttf"):
    font_path = Path("C:/Windows/Fonts") / font_name
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
app.setFont(QFont("Microsoft YaHei", 10))
ns = v3_launcher.load_v3_namespace()
client_update_ui.load_config = lambda *_args: {"enabled": False}
client_update_ui.acknowledge_startup = lambda *_args: None
ns["MainWindow"].load_catalogs = lambda self: None
ns["ApiWorker"].run = lambda self: self.failed.emit("offline dimension tests")
import quote_scheme_center
quote_scheme_center.QuoteSchemeWorker.run = lambda self: self.failed.emit("offline dimension tests")


class DimensionUiTests(unittest.TestCase):
    def setUp(self):
        screen = Mock(wraps=app.primaryScreen())
        screen.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
        self.screen_patch = patch.object(ns["MainWindow"], "screen", return_value=screen)
        self.screen_patch.start()
        self.addCleanup(self.screen_patch.stop)
        self.warning_patch = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.warning_patch.start()
        self.addCleanup(self.warning_patch.stop)
        self.w = ns["MainWindow"]()
        self.w.show()
        app.processEvents()

    def tearDown(self):
        self.w._scheme2_dirty = False
        self.w.deleteLater()
        app.processEvents()

    def apply(self, **fields):
        item = {"candidate_id": "synthetic-cabinet", "name": "离线合成柜", "raw_text": "", **deepcopy(fields)}
        self.w.active_drawing = item
        self.w._apply_confirmed_drawing_to_quote(item)
        app.processEvents()
        # No catalogue is loaded in this offline fixture. Enable only the
        # editor under test, as it is after a product catalogue is available.
        self.w.quote_spec_edit.setEnabled(True)
        return item

    def test_legacy_axes_reach_current_core_with_correct_order(self):
        item = self.apply(dimensions=[(800, 1800, 600)])
        self.assertEqual(self.w.quote_spec_edit.text(), "800*600*1800")
        self.assertEqual((self.w.width_spin.value(), self.w.height_spin.value(), self.w.depth_spin.value()), (800, 1800, 600))
        self.assertFalse(item["dimension_review_required"])

    def test_specification_without_legacy_tuple_now_fills_the_size(self):
        self.apply(specification="900*500*1700")
        self.assertEqual((self.w.width_spin.value(), self.w.height_spin.value(), self.w.depth_spin.value()), (900, 1700, 500))

    def test_actual_core_base_parser_keeps_body_price_height(self):
        item = self.apply(specification="800*600*(1800+100)")
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertEqual(self.w.height_spin.value(), 1800)
        self.assertEqual(self.w.quote_spec_edit.text(), "800*600*(1800+100)")

    def test_parser_does_not_forge_manual_provenance(self):
        item = repair_recognition_result({"specification": "800*600*(1800+100)", "specification_confidence": .91}, ns["parse_review_specification"])
        self.assertEqual(item["specification_confidence"], .91)
        self.assertNotEqual(item.get("dimension_source"), "manual_review")
        self.assertNotIn("manual_reviewed", item)

    def test_missing_size_clears_previous_visible_size_and_cache(self):
        self.apply(specification="900*500*1700")
        self.w.current_result = {"sentinel": "old quote"}
        item = self.apply(partial_specification_dimensions={"W": 800, "D": 600})
        self.assertEqual(self.w.quote_spec_edit.text(), "")
        self.assertEqual(self.w.quote_spec_edit.placeholderText(), "800*600*?")
        self.assertIsNone(self.w.current_result)
        self.assertEqual(self.w.scheme2_provenance_labels["dimensions"].text(), "待核对")
        self.assertFalse(item["verified"])
        self.assertFalse(item["manual_reviewed"])

    def test_pending_size_stops_before_attachment_or_quote_requests(self):
        self.apply(partial_specification_dimensions={"W": 800})
        self.w.resolve_attachments_for_quote = Mock()
        with patch.object(self.w, "calculate") as calculate:
            ui._calculate_and_add(self.w)
            calculate.assert_not_called()
        self.w.resolve_attachments_for_quote.assert_not_called()
        self.assertEqual(self.warning.call_args.args[1], "尺寸待核对")

    def native_candidate(self, units="mm"):
        from native_dimension_lines import inspect_single_page_pdf
        from verify_native_dimension_lines import diagram
        with tempfile.TemporaryDirectory(prefix="native-line-ui-") as folder:
            path = Path(folder) / "synthetic.pdf"
            diagram(path, units=units)
            evidence = inspect_single_page_pdf(path)["dimension_lines"]
        return repair_recognition_result({}, ns["parse_review_specification"], native_dimension_lines=evidence)

    def test_native_line_candidate_reaches_tooltip_and_still_requires_manual_size(self):
        item = self.apply(**self.native_candidate())
        self.assertEqual(self.w.quote_spec_edit.text(), "")
        self.assertEqual(self.w.scheme2_provenance_labels["dimensions"].text(), "待核对")
        self.assertIn("800*600*1800（尺寸线候选，待核对）", self.w.quote_spec_edit.toolTip())
        self.assertIn("高度是否包含底座", self.w.quote_spec_edit.toolTip())
        self.assertFalse(ui._prepare_recognized_dimensions(self.w))
        evidence = deepcopy(item["native_dimension_lines"])
        QTest.keyClicks(self.w.quote_spec_edit, "800*600*(1700+100)")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertEqual(item["dimensions"], [(800, 1700, 600)])
        self.assertEqual(item["native_dimension_lines"], evidence)

    def test_unit_unverified_candidate_does_not_fill_numeric_placeholder(self):
        self.apply(**self.native_candidate(units=""))
        self.assertEqual(self.w.quote_spec_edit.placeholderText(), "?*?*?")
        self.assertIn("单位待核", self.w.quote_spec_edit.toolTip())
        self.assertEqual(self.w.quote_spec_edit.text(), "")

    def test_switching_to_unrecognized_page_cannot_quote_the_previous_page(self):
        previous = self.apply(specification="900*500*1700")
        self.w.current_result = {"sentinel": "previous page"}
        self.w._scheme2_drawing_pages = [
            {"key": "page-1", "source_path": "synthetic.pdf", "page_index": 0, "page_count": 2, "item": previous, "state": None, "visited": True},
            {"key": "page-2", "source_path": "synthetic.pdf", "page_index": 1, "page_count": 2, "item": None, "state": None},
        ]
        self.w._scheme2_drawing_page_index = 0
        with patch.object(ui, "_show_scheme2_source_page"):
            ui._activate_scheme2_page(self.w, 1)
        self.assertEqual(self.w.quote_spec_edit.text(), "")
        self.assertIsNone(self.w.current_result)
        self.assertEqual(self.w.active_drawing["source_page_number"], 2)
        self.assertFalse(ui._prepare_recognized_dimensions(self.w))
        ui._finish_scheme2_page_recognition(self.w, "page-2", {"cabinet_candidates": [{"specification": "800*600*1800"}]})
        self.assertEqual(self.w.quote_spec_edit.text(), "800*600*1800")
        self.assertEqual(self.w.active_drawing["source_page_number"], 2)

    def test_late_page_result_preserves_manual_dimension_input(self):
        self.w._scheme2_drawing_pages = [{"key": "page-1", "source_path": "synthetic.pdf", "page_index": 0,
            "page_count": 1, "item": None, "state": None}]
        with patch.object(ui, "_show_scheme2_source_page"):
            ui._activate_scheme2_page(self.w, 0)
        self.w.quote_spec_edit.setEnabled(True)
        QTest.keyClicks(self.w.quote_spec_edit, "750*550*1650")
        ui._finish_scheme2_page_recognition(self.w, "page-1", {"cabinet_candidates": [{"specification": "800*600*1800"}]})
        self.assertEqual(self.w.quote_spec_edit.text(), "750*550*1650")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertEqual(self.w.active_drawing["dimensions"], [(750, 1650, 550)])

    def test_direct_calculate_and_add_cannot_use_previous_dimensions(self):
        self.apply(specification="900*500*1700")
        self.apply()
        self.w.calculate()
        self.w.add_current_to_summary()
        self.assertEqual(len(self.w.draft_items), 0)
        self.assertFalse(self.w.quote_calculation_in_progress)
        self.assertEqual(self.warning.call_count, 2)

    def test_error_result_cannot_be_marked_as_verified_size(self):
        item = self.apply(error="synthetic recognition failed", specification="800*600*1800", dimensions=[(800, 1800, 600)])
        self.assertTrue(item["dimension_review_required"])
        self.assertFalse(item["verified"])
        self.assertEqual(self.w.quote_spec_edit.text(), "")

    def test_manual_edit_resolves_conflict_without_changing_ocr_evidence(self):
        consensus = {"status": "conflict", "engine_candidates": {
            "windows": [{"specification": "800*600*1800"}], "rapidocr": [{"specification": "900*600*1800"}]}}
        item = self.apply(ocr_consensus=consensus)
        QTest.keyClicks(self.w.quote_spec_edit, "800*600*1800")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertFalse(item["dimension_review_required"])
        self.assertEqual(item["dimension_recognition"]["status"], "manual")
        self.assertEqual(item["ocr_consensus"], consensus)
        self.warning.assert_not_called()

    def test_invalid_manual_text_does_not_accept_hidden_defaults(self):
        item = self.apply()
        QTest.keyClicks(self.w.quote_spec_edit, "800*600*?")
        self.assertFalse(ui._prepare_recognized_dimensions(self.w))
        self.assertTrue(item["dimension_review_required"])
        self.assertEqual(item["dimensions"], [])

    def test_manual_base_correction_prices_body_height(self):
        item = self.apply()
        QTest.keyClicks(self.w.quote_spec_edit, "800*600*(1800+100)")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertEqual(self.w.height_spin.value(), 1800)

    def test_manual_split_width_preserves_current_ganged_parser_convention(self):
        item = self.apply()
        QTest.keyClicks(self.w.quote_spec_edit, "(800+900)*600*1800")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertEqual(item["specification"], "(800+900)*600*1800")
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertEqual(self.w.width_spin.value(), 800)
        self.assertEqual(len(self.w.ganged_cabinets), 2)

    def test_manual_dimension_preservation_keeps_both_text_and_numeric_axes(self):
        self.apply(specification="800*600*1800")
        self.w.scheme2_manual_fields.add("dimensions")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.apply(specification="900*700*2000")
        self.assertEqual(self.w.quote_spec_edit.text(), "800*600*1800")
        self.assertEqual((self.w.width_spin.value(), self.w.height_spin.value(), self.w.depth_spin.value()), (800, 1800, 600))

    def test_visual_states_use_existing_dimension_field(self):
        output = ROOT / ".codex-tmp" / "d-recognition-dimensions"
        output.mkdir(parents=True, exist_ok=True)
        self.apply(specification="800*600*1800")
        self.assertTrue(self.w.scheme2_dimension_field.grab().save(str(output / "recognized.png")))
        self.apply(partial_specification_dimensions={"W": 800, "D": 600})
        self.assertTrue(self.w.scheme2_dimension_field.grab().save(str(output / "pending.png")))
        QTest.keyClicks(self.w.quote_spec_edit, "800*600*1800")
        self.assertTrue(ui._prepare_recognized_dimensions(self.w))
        self.assertTrue(self.w.scheme2_dimension_field.grab().save(str(output / "manual.png")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
