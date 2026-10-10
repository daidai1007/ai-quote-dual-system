"""Offline regression for independently sized inner doors on ganged children."""
import copy
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
import attachment_v2_client as v2
from attachment_category_browser import final_attachment_quantity, match_named_quick_attachment_size
import layout_refresh
from quick_discount_rules import effective_attachment_quantity
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
app.setFont(QFont("Microsoft YaHei", 9))
CATALOG = [dict(attachment_price_id=identifier, category_level1="控制柜附件",
                category_level2="内门", item_name="内门", width_mm=width,
                height_mm=height, model_code=f"DOOR-{width}-{height}", price=price)
           for identifier, width, height, price in [(81, 800, 1800, 448.31),
                                                   (61, 600, 1800, 400),
                                                   (62, 600, 2100, 460)]]
CHILDREN = [dict(width_mm=800, height_mm=1800, depth_mm=800, base_height_mm=100),
            dict(width_mm=600, height_mm=1800, depth_mm=800, base_height_mm=100)]
CHOICE = {**CATALOG[0], "quantity": 1, "selection_source": "manual"}


def window_for(children=None):
    return SimpleNamespace(ganged_cabinets=copy.deepcopy(CHILDREN if children is None else children),
                           selected_product_code=lambda: "JP")


def expand(window=None, rows=None, catalog=None):
    return v2.expand_ganged_inner_doors_for_quote(
        window or window_for(), copy.deepcopy([CHOICE] if rows is None else rows),
        copy.deepcopy(CATALOG if catalog is None else catalog), "offline")


class GangedInnerDoors(unittest.TestCase):
    def test_first_child_id_and_model_do_not_pin_other_children(self):
        original = copy.deepcopy(CHOICE)
        rows, missing = expand()
        self.assertEqual(missing, [])
        self.assertEqual([row["attachment_price_id"] for row in rows], [81, 61])
        self.assertEqual([row["ganged_cabinet_index"] for row in rows], [0, 1])
        self.assertEqual([row["quantity"] for row in rows], [1, 1])
        self.assertTrue(all(row["ganged_inner_door_match"] for row in rows))
        self.assertEqual(CHOICE, original)

    def test_identical_children_still_have_independent_rows(self):
        rows, missing = expand(window_for([CHILDREN[0], CHILDREN[0]]))
        self.assertEqual(missing, [])
        self.assertEqual([row["attachment_price_id"] for row in rows], [81, 81])
        self.assertEqual([row["ganged_cabinet_index"] for row in rows], [0, 1])

    def test_existing_size_rule_is_used_for_each_child_not_base_height(self):
        children = copy.deepcopy(CHILDREN)
        children[1]["height_mm"] = 2000
        rows, missing = expand(window_for(children))
        self.assertEqual(missing, [])
        expected = match_named_quick_attachment_size(CATALOG, "控制柜附件", "内门", "内门",
                                                    (600, 2000, 800))
        self.assertEqual(rows[1]["attachment_price_id"], expected["attachment_price_id"])
        self.assertEqual(rows[1]["unit_price_override"], expected["unit_price_override"])
        self.assertEqual(rows[1]["size_match_target_height_mm"], 2000)

    def test_single_cabinet_custom_and_unrelated_attachments_unchanged(self):
        self.assertEqual(expand(window_for([CHILDREN[0]])), ([CHOICE], []))
        others = [{"item_name": "风机", "quantity": 3}, {**CHOICE, "custom": True}]
        self.assertEqual(expand(rows=others), (others, []))
        rows, missing = expand(rows=[others[0], CHOICE, others[1]])
        self.assertEqual(missing, [])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], others[0])
        self.assertEqual(rows[-1], others[1])

    def test_rematching_preserves_child_quantity_and_local_price(self):
        window = window_for()
        rows, _ = expand(window)
        rows[1].update(quantity=2, cost_quantity_manual=True, unit_price_override=333)
        again, missing = expand(window, rows)
        self.assertEqual(missing, [])
        self.assertEqual(len(again), 2)
        self.assertEqual(again[1]["quantity"], 2)
        self.assertEqual(again[1]["unit_price_override"], 333)
        # Editing/closing the popup must retain the catalogue identity on reopen.
        parent = QWidget()
        parent.refresh_summary = lambda: None
        item = {"attachments": again, "formula": {}, "quick": {}}
        editor = ui.AttachmentEditor(parent, item)
        editor.accept()
        self.assertEqual([row["item_name"] for row in item["attachments"]], ["内门", "内门"])
        reopened = ui.AttachmentEditor(parent, item)
        self.assertEqual(reopened.table.item(1, 0).text(), "柜体2｜内门")
        reopened.close()
        parent.close()
        window.attachments = again
        self.assertFalse(v2.needs_ganged_inner_door_resolution(window))
        window.ganged_cabinets[1]["height_mm"] = 2100
        self.assertTrue(v2.needs_ganged_inner_door_resolution(window))
        changed, missing = expand(window, again)
        self.assertEqual(missing, [])
        self.assertEqual(changed[1]["attachment_price_id"], 62)
        self.assertNotEqual(changed[1].get("unit_price_override"), 333)

    def test_missing_or_invalid_dimensions_report_named_child(self):
        rows, missing = expand(catalog=[])
        self.assertEqual(rows, [])
        self.assertEqual(missing, ["柜体1内门", "柜体2内门"])
        children = copy.deepcopy(CHILDREN)
        children[1]["width_mm"] = 0
        rows, missing = expand(window_for(children))
        self.assertEqual(len(rows), 1)
        self.assertEqual(missing, ["柜体2内门尺寸"])

    def test_popup_labels_payload_and_quantity_are_child_specific(self):
        rows, _ = expand()
        window = window_for()
        window.attachments = rows
        payload = layout_refresh._build_ganged_attachment_payload(window, [{}, {}])
        self.assertEqual([row["ganged_cabinet_index"] for row in payload["attachments"]], [0, 1])
        self.assertEqual([row["ganged_cabinet_index"] for row in v2.confirmation_inputs(rows)], [0, 1])
        parent = QWidget()
        parent.refresh_summary = lambda: None
        editor = ui.AttachmentEditor(parent, {"attachments": rows, "formula": {}, "quick": {}})
        self.addCleanup(parent.close)
        self.addCleanup(editor.close)
        self.assertEqual([editor.table.item(i, 0).text() for i in range(2)],
                         ["柜体1｜内门", "柜体2｜内门"])
        self.assertEqual([editor.table.item(i, 1).text() for i in range(2)],
                         ["宽 800 × 高 1800 mm", "宽 600 × 高 1800 mm"])
        for index, row in enumerate(rows):
            self.assertTrue(ui._attachment_chip_text(row).startswith(f"柜体{index + 1}："))
            for calculator in (final_attachment_quantity, effective_attachment_quantity):
                self.assertEqual(calculator(row, 3, 2), 3)
                self.assertEqual(calculator({**row, "quantity": 2, "cost_quantity_manual": True}, 3, 2), 6)
        output = ROOT / "outputs" / "ganged-inner-doors.png"
        output.parent.mkdir(exist_ok=True)
        editor.show()
        editor.resize(800, 315)
        app.processEvents()
        editor.grab().save(str(output))

    def test_add_with_existing_id_still_resolves_before_calculation(self):
        window = window_for()
        window.attachments = [copy.deepcopy(CHOICE)]
        window.current_result = {"input_signature": "unchanged"}
        window.quote_input_signature = lambda: "unchanged"
        window.scheme2_add_button = QPushButton()
        calls = []
        window.calculate = lambda: calls.append("calculate")
        window.show_error = lambda message: self.fail(message)
        window.resolve_attachments_for_quote = lambda success, failure: (calls.append("resolve"), success())
        with patch.object(ui, "_monitor_formula_calculation"), patch.object(ui, "_finish_add") as finish:
            ui._calculate_and_add(window)
        self.assertEqual(calls, ["resolve", "calculate"])
        finish.assert_not_called()

    def test_actual_v3_resolver_expands_already_priced_choice(self):
        namespace = v3_launcher.load_v3_namespace()
        Window, Worker = namespace["MainWindow"], namespace["ApiWorker"]
        original_init = Worker.__init__
        requests, successes, failures = [], [], []

        def capture_init(worker, url, payload, parent=None, *args, **kwargs):
            requests.append(url)
            original_init(worker, url, payload, parent, *args, **kwargs)

        def start(worker):
            def respond():
                worker.succeeded.emit({"items": copy.deepcopy(CATALOG), "data_version": "offline"})
                worker.finished.emit()
            QTimer.singleShot(0, respond)

        with patch.object(Window, "load_catalogs", lambda self: None), \
             patch.object(Window, "refresh_formula_inputs", lambda self, *args: None), \
             patch.object(Worker, "__init__", capture_init), patch.object(Worker, "start", start):
            window = Window()
            self.addCleanup(window.close)
            window.ganged_cabinets = copy.deepcopy(CHILDREN)
            window.attachments = [copy.deepcopy(CHOICE)]
            window.resolve_attachments_for_quote(lambda: successes.append(True), failures.append)
            deadline = time.monotonic() + 2
            while not successes and not failures and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            self.assertEqual(failures, [])
            self.assertEqual(successes, [True])
            self.assertTrue(requests[-1].endswith("/api/attachments/catalog?v=2"))
            self.assertEqual([row["attachment_price_id"] for row in window.attachments], [81, 61])

    def test_jk_inner_doors_use_their_existing_catalogue_family(self):
        catalog = [{**row, "category_level1": "控制箱附件"} for row in CATALOG]
        choice = {**CHOICE, "category_level1": "控制箱附件"}
        rows, missing = expand(rows=[choice], catalog=catalog)
        self.assertEqual(missing, [])
        self.assertEqual([row["attachment_price_id"] for row in rows], [81, 61])
        self.assertTrue(all(row["category_level1"] == "控制箱附件" for row in rows))


if __name__ == "__main__":
    unittest.main()
