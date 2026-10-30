"""Offline dimension regressions: synthetic data/PDFs, no OCR or quote calls."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))
from recognition_dimensions import (dimension_review_hint, explicit_axis_evidence,
                                    parse_dimension_specification, reconcile_recognition_dimensions)
from recognition_repair import install_recognition_repair, repair_recognition_result


def synthetic_pdf(path, pages=1):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 700 Td (W={800+index*100} D=600 H=1800) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    writer.close()


class DimensionTests(unittest.TestCase):
    def test_legacy_whd_is_displayed_as_wdh(self):
        item = reconcile_recognition_dimensions({"dimensions": [(800, 1800, 600)]})
        self.assertEqual(item["specification"], "800*600*1800")
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])

    def test_specification_only_completes_axis_tuple(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*1800"})
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertNotIn("manual_reviewed", item)

    def test_mismatched_tuple_and_specification_do_not_choose_either(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*1800", "dimensions": [(800, 600, 1800)]})
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")
        self.assertEqual(len(item["dimension_recognition"]["candidates"]), 2)
        self.assertEqual(item["dimensions"], [])
        self.assertEqual(item["specification"], "")

    def test_multiple_legacy_sizes_are_not_sorted_or_first_selected(self):
        item = reconcile_recognition_dimensions({"dimensions": [(800, 1800, 600), (900, 2000, 700)]})
        self.assertTrue(item["dimension_review_required"])
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")

    def test_base_is_separate_from_pricing_body_height(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*(1800+100)", "dimensions": [(800, 1800, 600)]})
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertEqual(item["height_terms_mm"], [1800, 100])
        self.assertFalse(item["dimension_review_required"])

    def test_parser_metadata_never_implies_manual_review(self):
        def parser(text):
            return {**parse_dimension_specification(text), "dimension_source": "manual_review",
                    "specification_confidence": 1.0, "evidence": ["人工复核"], "manual_reviewed": True}
        item = reconcile_recognition_dimensions({"specification": "800*600*1800", "specification_confidence": 0.9}, parser)
        self.assertNotIn("dimension_source", item)
        self.assertNotIn("evidence", item)
        self.assertNotIn("manual_reviewed", item)
        self.assertEqual(item["specification_confidence"], 0.9)

    def test_native_axis_labels_can_recover_missing_dimensions(self):
        item = reconcile_recognition_dimensions({}, native_text="W=800 D=600 H=1800")
        self.assertEqual(item["specification"], "800*600*1800")
        self.assertEqual(item["dimension_source"], "pdf_native_explicit_axes")

    def test_native_units_and_declared_axis_order(self):
        for text in ("宽0.8m 深60cm 高1800mm", "外形尺寸（宽×高×深）：800×1800×600mm", "W*D*H: 800*600*1800"):
            with self.subTest(text=text):
                item = reconcile_recognition_dimensions({}, native_text=text)
                self.assertEqual(item["dimensions"], [(800, 1800, 600)])

    def test_unlabelled_native_triple_has_no_guessed_order(self):
        item = reconcile_recognition_dimensions({}, native_text="外形尺寸 800*600*1800")
        self.assertTrue(item["dimension_review_required"])

    def test_expression_range_unit_suffix_and_header_prefix_are_not_truncated(self):
        for text in ("W800+100 D600 H1800", "W800 D600 H1800 + 100", "W800 D600 H1800cm2",
                     "LW*D*H: 800*600*1800", "W800-900 D600 H1800", "W1,200 D600 H1800",
                     "W800 D600 H1800-1900", "W*D*H: 800*600*1800+100",
                     "W800 D600 H1800 mm2", "W800 D600 H180 cm2", "W800 D600 H1800 inch"):
            with self.subTest(text=text):
                item = reconcile_recognition_dimensions({}, native_text=text)
                self.assertTrue(item["dimension_review_required"])
                self.assertEqual(item["specification"], "")

    def test_partial_native_counter_evidence_blocks_complete_specification(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*1800"}, native_text="W900")
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")

    def test_ocr_axis_conflict_is_not_hidden_by_a_complete_specification(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*1800", "raw_text": "W800 W900 D600 H1800"})
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")

    def test_total_height_partial_is_compared_in_body_height_semantics(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*(1800+100)", "raw_text": "总高1900 底座100"})
        self.assertFalse(item["dimension_review_required"])

    def test_component_dimensions_do_not_complete_cabinet(self):
        item = reconcile_recognition_dimensions({}, native_text="W800 D600\n安装板 H1600\n门板 H1700")
        self.assertEqual(item["dimension_recognition"]["status"], "partial")
        self.assertNotIn("H", item["partial_specification_dimensions"])

    def test_two_named_widths_in_native_text_remain_conflicting(self):
        item = reconcile_recognition_dimensions({}, native_text="W800 D600 H1800\nW900 D600 H1800")
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")
        self.assertEqual(item["specification"], "")

    def test_total_height_and_base_can_resolve_body_when_all_axes_named(self):
        item = reconcile_recognition_dimensions({}, native_text="宽800 深600 总高1900 底座100")
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])
        self.assertEqual(item["specification"], "800*600*(1800+100)")

    def test_explicit_body_height_and_base(self):
        item = reconcile_recognition_dimensions({}, native_text="宽800 深600 本体高1800 底座高100")
        self.assertEqual(item["specification"], "800*600*(1800+100)")

    def test_unqualified_height_with_base_does_not_guess_body_or_overall(self):
        item = reconcile_recognition_dimensions({}, native_text="宽800 深600 高1900 底座100")
        self.assertTrue(item["dimension_review_required"])
        self.assertEqual(item["specification"], "")

    def test_ambiguous_height_and_base_cannot_be_bypassed_by_legacy_size(self):
        for old in ({"specification": "800*600*1900"}, {"dimensions": [(800, 1900, 600)]}):
            item = reconcile_recognition_dimensions(old, native_text="W800 D600 H1900 B100")
            self.assertTrue(item["dimension_review_required"])
            self.assertEqual(item["specification"], "")

    def test_explicit_base_specification_keeps_its_resolved_body_semantics(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*(1800+100)"}, native_text="W800 D600 H1900 B100")
        self.assertFalse(item["dimension_review_required"])
        self.assertEqual(item["dimensions"], [(800, 1800, 600)])

    def test_partial_total_height_is_not_described_as_body(self):
        item = reconcile_recognition_dimensions({"raw_text": "总高1900 底座100"})
        self.assertNotIn("本体高1900", dimension_review_hint(item))

    def test_ocr_text_labels_do_not_bypass_existing_engine_gate(self):
        item = reconcile_recognition_dimensions({"raw_text": "W800 D600 H1800"})
        self.assertEqual(item["specification"], "")
        self.assertEqual(item["partial_specification_dimensions"], {"W": 800, "D": 600, "H": 1800})

    def test_single_engine_confirmation_requirement_is_preserved(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*1800", "dimensions": [(800, 1800, 600)],
            "ocr_consensus": {"status": "single_engine"}, "ocr_confirmation_required": True, "specification_confidence": 0.86})
        self.assertTrue(item["dimension_review_required"])
        self.assertEqual(item["dimension_recognition"]["status"], "unverified")

    def test_base_conflict_cannot_hide_behind_dimension_agreement(self):
        item = reconcile_recognition_dimensions({"specification": "800*600*(1800+100)", "dimensions": [(800, 1800, 600)],
            "ocr_consensus": {"status": "agreed"}, "ocr_base_evidence": {"status": "conflict"}})
        self.assertEqual(item["dimension_recognition"]["status"], "conflict")

    def test_conflicting_engine_candidates_are_retained(self):
        item = reconcile_recognition_dimensions({"ocr_consensus": {"status": "conflict", "engine_candidates": {
            "windows": [{"specification": "800*600*1800"}], "rapidocr": [{"specification": "900*600*1800"}]}}})
        self.assertEqual({row["origin"] for row in item["dimension_recognition"]["candidates"]}, {"windows", "rapidocr"})
        self.assertTrue(item["dimension_review_required"])

    def test_low_confidence_and_review_only_are_not_promoted(self):
        for flags in ({"specification_confidence": 0.5}, {"specification_review_only": True}):
            item = reconcile_recognition_dimensions({"dimensions": [(800, 1800, 600)], **flags})
            self.assertTrue(item["dimension_review_required"])

    def test_invalid_or_missing_dimensions_never_receive_defaults(self):
        for dimensions in ([], [(800, 0, 600)], [(800, float('nan'), 600)], [(800, float('inf'), 600)], [(True, 1800, 600)]):
            item = reconcile_recognition_dimensions({"dimensions": dimensions})
            self.assertEqual(item["specification"], "")

    def test_parser_rejects_unbalanced_parentheses_or_height_with_unknown_terms(self):
        for text in ("(800*600*1800", "800)*600*1800", "800*600*(1700+100+100)", "800*0*1800"):
            self.assertIsNone(parse_dimension_specification(text))

    def test_repeated_identical_evidence_is_one_size(self):
        item = reconcile_recognition_dimensions({"dimensions": [(800, 1800, 600), (800, 1800, 600)]})
        self.assertFalse(item["dimension_review_required"])


class RepairScopeTests(unittest.TestCase):
    @staticmethod
    def geometry(widths=(800,)):
        return {"rapidocr": {"geometry_policy": "landscape_engineering_sheet", "tokens": [
            *({"text": str(width), "confidence": .99, "center_x": .5, "center_y": .1, "orientation": "horizontal"} for width in widths),
            {"text": "600", "confidence": .99, "center_x": .2, "center_y": .3, "orientation": "horizontal"}]}}

    def test_geometry_retains_only_unique_partial_axes_and_never_height(self):
        item = repair_recognition_result({"ocr_engine_evidence": self.geometry((800, 900))})
        self.assertEqual(item["partial_specification_dimensions"], {"D": 600})
        self.assertEqual(item["dimensions"], [])

    def test_multicabinet_copied_document_geometry_is_not_candidate_evidence(self):
        evidence = self.geometry()
        item = repair_recognition_result({"ocr_engine_evidence": evidence,
            "cabinet_candidates": [{"ocr_engine_evidence": deepcopy(evidence)}, {"ocr_engine_evidence": deepcopy(evidence)}]}, native_text="W800 D600 H1800")
        for row in item["cabinet_candidates"]:
            self.assertEqual(row["partial_specification_dimensions"], {})
            self.assertEqual(row["specification"], "")

    def test_dummy_region_with_no_position_allows_single_cabinet_native_evidence(self):
        item = repair_recognition_result({"cabinet_candidates": [{"source_region": {"key": "whole", "x": None, "y": None}}]}, native_text="W800 D600 H1800")
        self.assertEqual(item["cabinet_candidates"][0]["specification"], "800*600*1800")

    def test_real_region_does_not_inherit_unscoped_page_text(self):
        item = repair_recognition_result({"cabinet_candidates": [{"source_region": {"x": .4, "y": .2}}]}, native_text="W800 D600 H1800")
        self.assertTrue(item["cabinet_candidates"][0]["dimension_review_required"])

    def test_malformed_tokens_do_not_fail_the_batch(self):
        evidence = self.geometry()
        evidence["rapidocr"]["tokens"] += [None, {"text": "900", "confidence": "bad"}]
        item = repair_recognition_result({"ocr_engine_evidence": evidence, "partial_specification_dimensions": {"H": "bad"}})
        self.assertNotIn("H", item["partial_specification_dimensions"])

    def test_native_pdf_wrapper_uses_synthetic_page_without_calling_ocr(self):
        class Tools:
            @classmethod
            def recognize_document(cls, path):
                return {"cabinet_candidates": [{"source_region": {"x": None, "y": None}}]}
        install_recognition_repair({"DrawingRecognitionTools": Tools})
        with tempfile.TemporaryDirectory(prefix="dimension-native-offline-") as folder:
            path = Path(folder) / "synthetic.pdf"
            synthetic_pdf(path)
            item = Tools.recognize_document(str(path))
            self.assertEqual(item["cabinet_candidates"][0]["dimensions"], [(800, 1800, 600)])

    def test_unsplit_multipage_pdf_is_not_collapsed_to_one_size(self):
        class Tools:
            @classmethod
            def recognize_document(cls, path):
                return {}
        install_recognition_repair({"DrawingRecognitionTools": Tools})
        with tempfile.TemporaryDirectory(prefix="dimension-pages-offline-") as folder:
            path = Path(folder) / "synthetic.pdf"
            synthetic_pdf(path, pages=2)
            self.assertTrue(Tools.recognize_document(str(path))["dimension_review_required"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
