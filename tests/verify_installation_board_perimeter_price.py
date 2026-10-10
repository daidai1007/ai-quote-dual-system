"""Focused offline checks for installation-board selection and V2 pricing."""
import copy
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import attachment_v2_client as v2
from attachment_category_browser import match_installation_board_size
import scheme2_ui as ui
import v3_launcher

BOARD = dict(attachment_price_id=1, category_level1="安装板", item_name="安装板",
             model_code="BOARD-600", width_mm=600, height_mm=1800, depth_mm=600,
             price=363.51, quantity=1)
app = QApplication.instance() or QApplication([])


class BoardPerimeterPrice(unittest.TestCase):
    def test_nearest_perimeter_precedes_shape_distance(self):
        near_shape = {**BOARD, "width_mm": 950, "height_mm": 1950}
        near_perimeter = {**BOARD, "attachment_price_id": 2, "width_mm": 500, "height_mm": 2450}
        exact = {**BOARD, "attachment_price_id": 3, "width_mm": 1000, "height_mm": 2000}
        for rows in ([near_shape, near_perimeter], [near_perimeter, near_shape]):
            matched = match_installation_board_size(rows, BOARD, (1000, 2000, 999))
            self.assertEqual(matched["attachment_price_id"], 2)
            self.assertAlmostEqual(matched["size_match_ratio"], 6000 / 5900)
        same_perimeter = {**BOARD, "width_mm": 600, "height_mm": 2400}
        matched = match_installation_board_size([same_perimeter, exact], BOARD, (1000, 2000, 0))
        self.assertEqual(matched["attachment_price_id"], 3)
        self.assertNotIn("unit_price_override", matched)

    def test_existing_model_does_not_pin_size_or_bypass_price_scaling(self):
        exact = {**BOARD, "attachment_price_id": 2, "model_code": "BOARD-500",
                 "width_mm": 500, "height_mm": 1700, "price": 300}
        matched = v2.match_catalog_attachment(BOARD, [BOARD, exact],
                                             target_dimensions=(500, 1700, 600), product_code="JP")
        self.assertEqual(matched["attachment_price_id"], 2)
        nearest = v2.match_catalog_attachment(BOARD, [BOARD],
                                             target_dimensions=(500, 1700, 900), product_code="JP")
        self.assertEqual(nearest["unit_price_override"], 333.2175)

    def test_older_api_amount_uses_ratio_quantity_and_sign_without_compounding(self):
        source = match_installation_board_size([BOARD], BOARD, (500, 1700, 900))
        original = copy.deepcopy(BOARD)
        for quantity, sign, expected in ((1, 1, 333.22), (3, 1, 999.65), (2, -1, -666.44)):
            source.update(quantity=quantity, attachment_price_sign=sign)
            cost = dict(quick_amount=round(363.51*quantity*sign, 2), quantity=quantity,
                        matched_price=363.51, face_price=363.51, formula_amount=50.83)
            merged = v2.merge_cost(source, cost)
            self.assertEqual(merged["quick_amount"], expected)
            self.assertEqual(v2.merge_cost(merged, cost)["quick_amount"], expected)
            self.assertEqual(merged["formula_amount"], 50.83)
        self.assertEqual(BOARD, original)
        source["quick_amount_override"] = 123.45
        self.assertEqual(v2.merge_cost(source, cost)["quick_amount"], 123.45)
        source["unit_price_override"] = 61.725
        merged = v2.merge_cost(source, {**cost, "size_match_ratio": .9, "unit_price_override": 300})
        self.assertEqual(merged["quick_amount"], 123.45)
        self.assertEqual(merged["unit_price_override"], 61.725)

    def test_rematch_replaces_old_ratio_and_preserves_manual_amount(self):
        old = match_installation_board_size([BOARD], BOARD, (500, 1700, 600))
        old.update(quantity=3, attachment_price_sign=-1, quick_amount=-999)
        exact = match_installation_board_size([BOARD], BOARD, (600, 1800, 600))
        resolved = v2.resolve_installation_board(old, exact, "offline")
        self.assertNotIn("unit_price_override", resolved)
        self.assertNotIn("quick_amount", resolved)
        self.assertEqual(resolved["quantity"], 3)
        self.assertEqual(resolved["attachment_price_sign"], -1)
        old.update(quick_amount_override=25, unit_price_override=8.333333)
        self.assertEqual(v2.resolve_installation_board(old, exact, "offline")["quick_amount_override"], 25)

    def test_actual_v3_resolves_already_selected_id_and_popup_shows_scaled_amount(self):
        ns = v3_launcher.load_v3_namespace()
        Window, Worker = ns["MainWindow"], ns["ApiWorker"]
        requests = []
        original_init = Worker.__init__

        def capture(worker, url, payload, parent=None, *args, **kwargs):
            requests.append(url)
            original_init(worker, url, payload, parent, *args, **kwargs)

        def start(worker):
            def respond():
                worker.succeeded.emit({"items": [copy.deepcopy(BOARD)], "data_version": "offline"})
                worker.finished.emit()
            QTimer.singleShot(0, respond)

        with patch.object(Window, "load_catalogs", lambda self: None), \
             patch.object(Window, "refresh_formula_inputs", lambda self, *args: None), \
             patch.object(Worker, "__init__", capture), patch.object(Worker, "start", start):
            window = Window()
            self.addCleanup(window.close)
            window.quote_spec_edit.setText("500*900*(1700+100)")
            window.attachments = [copy.deepcopy(BOARD)]
            self.assertTrue(v2.needs_installation_board_resolution(window))
            success, errors = [], []
            window.resolve_attachments_for_quote(lambda: success.append(True), errors.append)
            deadline = time.monotonic() + 2
            while not success and not errors and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            self.assertEqual(errors, [])
            self.assertEqual(success, [True])
            self.assertTrue(requests[-1].endswith("/api/attachments/catalog?v=2"))
            self.assertFalse(v2.needs_installation_board_resolution(window))
            selected = window.attachments[0]
            self.assertEqual(selected["unit_price_override"], 333.2175)
            selected = v2.merge_cost(selected, dict(quick_amount=363.51, formula_amount=50.83))
            self.assertEqual(ui.AttachmentEditor._display_amounts(selected), (50.83, 333.22))
            # The actual V3 result adapter must update the quick total too,
            # not merely fix the popup amount after a legacy API response.
            window.pending_quote_signature = window.quote_input_signature()
            window._v2_request_environment = None
            window.show_result({"quote_id": "offline", "attachment_contract": 2,
                "quote_line_id": "offline-line", "attachments": [dict(item_name="安装板",
                    attachment_price_id=1, quantity=1, face_price=363.51, matched_price=363.51,
                    quick_amount=363.51, formula_amount=50.83)],
                "formula_cost": dict(material_cost=100, auxiliary_cost=10, labor_cost=20,
                    spray_cost=30, management_fee=2.6, attachment_fee=50.83, total_cost=213.43,
                    product_area_m2=4, corrected_material_weight_kg=66.1, net_material_weight_kg=55),
                "quick_quote": dict(base_price=1000, attachment_fee=363.51, total_cost=1363.51,
                    matched_experience={}, match_method="exact"), "risk_flags": []})
            self.assertEqual(window.current_result["quick"]["attachment_fee"], 333.22)
            self.assertEqual(window.current_result["quick"]["total_cost"], 1333.22)


if __name__ == "__main__":
    unittest.main()
