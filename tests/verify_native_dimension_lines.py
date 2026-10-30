"""Synthetic vector PDF regressions. No OCR models, network, Qt or business DB."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))
from native_dimension_lines import attach_dimension_line_suggestions, inspect_single_page_pdf
from recognition_dimensions import dimension_review_hint
from recognition_repair import install_recognition_repair, repair_recognition_result


def diagram(path, *, broken=False, side_height=1800, units="mm", duplicate_front=False,
            captions=True, numbers=True, rotated=False, transform=False, hidden=False,
            extra_width=False, unpainted=False, spaced_width=False, form=False):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=840, height=900)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    commands = []
    if form:
        form_stream = DecodedStreamObject()
        form_stream.set_data(b"")
        form_stream[NameObject("/Subtype")] = NameObject("/Form")
        page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Fm1"): writer._add_object(form_stream)})
        commands += ["/Fm1 Do"]
    if transform:
        commands += ["q .8 0 0 .8 20 20 cm"]
    paint = "n" if unpainted else "S"
    commands += [f"100 250 200 450 re {paint}", f"450 250 150 450 re {paint}", "50 30 700 90 re S"]
    if broken:
        commands += ["100 730 m 185 730 l S", "215 730 m 300 730 l S"]
    else:
        commands += ["100 730 m 300 730 l S"]
    commands += ["450 730 m 600 730 l S", "70 250 m 70 700 l S", "630 250 m 630 700 l S"]
    if extra_width:
        commands += ["100 760 m 300 760 l S"]

    def text(value, x, y, vertical=False):
        matrix = f"0 1 -1 0 {x} {y}" if vertical else f"1 0 0 1 {x} {y}"
        mode = "3 Tr " if hidden else ""
        commands.append(f"BT /F1 12 Tf {mode}{matrix} Tm ({value}) Tj ET")

    if captions:
        text("FRONT VIEW", 170, 225)
        text("SIDE VIEW", 480, 225)
        if duplicate_front:
            text("FRONT VIEW", 170, 225)
    if numbers:
        if spaced_width:
            commands.append("BT /F1 12 Tf 1 0 0 1 190 738 Tm [(8) -1000 (00)] TJ ET")
        else:
            text("800", 190, 738)
        text("600", 515, 738)
        text("1800", 56, 460, True)
        text(str(side_height), 646, 460, True)
        text("9999", 260, 60)  # title block, never an overall dimension
        text("18", 170, 450)   # local internal annotation
        if extra_width:
            text("900", 190, 768)
    if units:
        text("UNITS:" + units, 60, 140)
    if transform:
        commands += ["Q"]
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotated:
        page.rotate(90)
    writer.write(path)
    writer.close()


class NativeLineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="native-dimensions-offline-")
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "diagram.pdf"

    def evidence(self, **options):
        diagram(self.path, **options)
        return inspect_single_page_pdf(str(self.path))

    def test_named_front_and_side_produce_corresponding_axes(self):
        evidence = self.evidence()["dimension_lines"]
        self.assertEqual(evidence["specification"], "800*600*1800")
        self.assertEqual(evidence["partial"], {"W": 800, "D": 600, "H": 1800})
        self.assertEqual(evidence["units"], "mm")
        self.assertEqual(evidence["policy"], "review_only_never_confirms_specification")

    def test_candidate_has_original_annotation_and_line_provenance(self):
        evidence = self.evidence()["dimension_lines"]
        width = next(row for row in evidence["observations"] if row["axis"] == "W")
        self.assertEqual(width["text"], "800")
        self.assertEqual(width["view_label"], "FRONT VIEW")
        self.assertEqual(width["line"]["orientation"], "horizontal")
        self.assertEqual(width["view_box"], [100, 250, 300, 700])

    def test_dimension_line_gap_for_number_is_supported(self):
        self.assertEqual(self.evidence(broken=True)["dimension_lines"]["specification"], "800*600*1800")

    def test_font_and_path_transform_use_same_pdf_space(self):
        self.assertEqual(self.evidence(transform=True)["dimension_lines"]["specification"], "800*600*1800")

    def test_title_block_and_local_number_are_excluded(self):
        values = {row["value"] for row in self.evidence()["dimension_lines"]["observations"]}
        self.assertNotIn(9999, values)
        self.assertNotIn(18, values)

    def test_caption_is_required_no_front_side_assignment_by_page_position(self):
        self.assertEqual(self.evidence(captions=False)["dimension_lines"]["status"], "unavailable")

    def test_without_numeric_text_nothing_is_inferred_from_pixel_span(self):
        self.assertEqual(self.evidence(numbers=False)["dimension_lines"]["partial"], {})

    def test_inconsistent_view_heights_are_not_collapsed(self):
        evidence = self.evidence(side_height=1900)["dimension_lines"]
        self.assertEqual(evidence["status"], "conflict")
        self.assertIsNone(evidence["specification"])
        self.assertEqual(evidence["axis_values"]["H"], [1800, 1900])

    def test_two_width_annotations_are_not_resolved_by_maximum(self):
        evidence = self.evidence(extra_width=True)["dimension_lines"]
        self.assertEqual(evidence["status"], "conflict")
        self.assertEqual(evidence["axis_values"]["W"], [800, 900])

    def test_duplicate_caption_does_not_invent_a_second_product(self):
        evidence = self.evidence(duplicate_front=True)["dimension_lines"]
        self.assertEqual(evidence["specification"], "800*600*1800")
        self.assertEqual(len(evidence["views"]), 2)

    def test_unpainted_clip_rectangles_are_not_cabinet_views(self):
        self.assertEqual(self.evidence(unpainted=True)["dimension_lines"]["views"], [])

    def test_hidden_ocr_layer_is_not_native_visible_annotation(self):
        self.assertEqual(self.evidence(hidden=True)["dimension_lines"]["status"], "unavailable")

    def test_rotation_has_explicit_geometry_limit_but_keeps_text(self):
        result = self.evidence(rotated=True)
        self.assertIn("800", result["text"])
        self.assertEqual(result["dimension_lines"]["status"], "unavailable")
        self.assertIn("rotation", result["dimension_lines"]["reason"])

    def test_widely_spaced_text_does_not_become_one_number_on_flush(self):
        evidence = self.evidence(spaced_width=True)["dimension_lines"]
        self.assertNotIn("W", evidence["partial"])
        self.assertIsNone(evidence["specification"])

    def test_form_xobject_disables_geometry_without_removing_text(self):
        result = self.evidence(form=True)
        self.assertIn("800", result["text"])
        self.assertEqual(result["dimension_lines"]["status"], "unavailable")
        self.assertIn("complex_form", result["dimension_lines"]["reason"])

    def test_geometry_limit_does_not_break_existing_native_text_recovery(self):
        with patch("native_dimension_lines._MAX_SEGMENTS", 1):
            result = self.evidence()
        self.assertIn("800", result["text"])
        self.assertEqual(result["dimension_lines"]["status"], "unavailable")
        self.assertEqual(result["dimension_lines"]["reason"], "EvidenceLimit")

    def test_custom_font_encoding_does_not_use_raw_ascii_character_codes(self):
        from native_dimension_lines import _Collector
        from pypdf.generic import DictionaryObject, NameObject
        font = DictionaryObject({NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): DictionaryObject()})
        page = {"/Resources": {"/Font": {"/F1": font}}}
        collector = _Collector(page)
        matrix = [1, 0, 0, 1, 190, 738]
        collector.operand(b"Tf", ["/F1", 12], matrix, matrix)
        collector.operand(b"Tj", [b"800"], matrix, matrix)
        self.assertEqual(collector.tokens, [])
        collector.text("600", matrix, [1, 0, 0, 1, 0, 0], font, 12)
        self.assertEqual(collector.tokens[0]["text"], "600")

    def test_missing_or_non_mm_units_are_not_silently_assumed(self):
        for unit in ("", "cm", "mm2"):
            evidence = self.evidence(units=unit)["dimension_lines"]
            self.assertEqual(evidence["units"], "unverified")
            item = repair_recognition_result({}, native_dimension_lines=evidence)
            self.assertEqual(item["dimension_recognition"]["partial"], {})
            self.assertIn("单位待核", dimension_review_hint(item))

    def test_geometry_never_auto_confirms_a_complete_size(self):
        evidence = self.evidence()["dimension_lines"]
        item = repair_recognition_result({}, native_dimension_lines=evidence)
        self.assertEqual(item["specification"], "")
        self.assertEqual(item["dimensions"], [])
        self.assertTrue(item["dimension_review_required"])
        self.assertNotIn("manual_reviewed", item)
        self.assertEqual(item["dimension_recognition"]["partial"], {"W": 800, "D": 600, "H": 1800})
        self.assertIn("尺寸线候选", dimension_review_hint(item))

    def test_known_size_and_original_ocr_evidence_are_not_overwritten(self):
        evidence = self.evidence()["dimension_lines"]
        item = repair_recognition_result({"specification": "900*500*1700", "dimensions": [(900, 1700, 500)]}, native_dimension_lines=evidence)
        self.assertEqual(item["specification"], "900*500*1700")
        self.assertFalse(item["dimension_review_required"])
        self.assertEqual(item["native_dimension_lines"], evidence)

    def test_multiple_products_do_not_inherit_unscoped_geometry(self):
        evidence = self.evidence()["dimension_lines"]
        item = repair_recognition_result({"cabinet_candidates": [{}, {}]}, native_dimension_lines=evidence)
        for row in item["cabinet_candidates"]:
            self.assertNotIn("native_dimension_lines", row)
            self.assertEqual(row["dimension_recognition"]["candidates"], [])

    def test_located_product_region_does_not_inherit_page_geometry(self):
        evidence = self.evidence()["dimension_lines"]
        item = repair_recognition_result({"source_region": {"x": .1, "y": .2}}, native_dimension_lines=evidence)
        self.assertNotIn("native_dimension_lines", item)

    def test_wrapper_adds_line_evidence_with_same_existing_ocr_engine(self):
        diagram(self.path)
        calls = []
        class ExistingTools:
            @classmethod
            def recognize_document(cls, path):
                calls.append(path)
                return {"cabinet_candidates": [{"source_region": {"x": None, "y": None}}]}
        install_recognition_repair({"DrawingRecognitionTools": ExistingTools})
        item = ExistingTools.recognize_document(str(self.path))
        self.assertEqual(calls, [str(self.path)])
        row = item["cabinet_candidates"][0]
        self.assertEqual(row["native_dimension_lines"]["specification"], "800*600*1800")
        self.assertTrue(row["dimension_review_required"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
