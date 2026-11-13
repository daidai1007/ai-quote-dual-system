"""Exercise child-specific catalogue selection through the desktop quote flow."""
import copy
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import attachment_v2_client as v2
from attachment_category_browser import final_attachment_quantity
import layout_refresh
import scheme2_ui as ui
import v3_launcher


APP = QApplication.instance() or QApplication([])
FAMILIES = (
    ("底座", "固定底座", "底座高度", 200),
    ("底座", "活动底座", "底座高度", 200),
    ("安装板", "安装板", None, 1800),
    ("控制柜附件", "防雨顶", None, 1800),
    ("安装附件", "分段板", "分段板高度", 150),
    ("控制柜附件", "内门", None, 1800),
    ("控制柜附件", "玻璃门", None, 1800),
    ("控制柜附件", "通风顶罩", "通风顶罩高度", 80),
)


def fixture():
    choices, catalog = [], []
    for index, (category, name, height_field, height) in enumerate(FAMILIES, 1):
        pair = [
            dict(attachment_price_id=10 * index + child, item_name=name,
                 category_level1=category, category_level2=name,
                 width_mm=width, depth_mm=height if name == "通风顶罩" else 600,
                 height_mm=600 if name == "通风顶罩" else height,
                 price=100 * index + child, catalog_version="offline")
            for child, width in enumerate((800, 1000))
        ]
        catalog.extend(pair)
        choices.append(dict(pair[0], quantity=1, manual_inputs={height_field: height} if height_field else {}))
    for identifier, category, name in ((91, "配置变形", "填充安装板"), (92, "其他附件", "丝印")):
        row = dict(attachment_price_id=identifier, item_name=name,
                   category_level1=category, price=25, catalog_version="offline")
        catalog.append(row)
        choices.append(dict(row, quantity=1))
    return choices, catalog


class GangedSizedAttachments(unittest.TestCase):
    def test_identical_catalogue_ids_keep_independent_popup_edits(self):
        choices, catalog = fixture()
        board = next(row for row in choices if row["item_name"] == "安装板")
        window = SimpleNamespace(
            ganged_cabinets=[dict(width_mm=width, height_mm=1800, depth_mm=600) for width in (800, 1000)],
            selected_product_code=lambda: "JP",
        )
        board_catalog = [row for row in catalog if row["attachment_price_id"] == board["attachment_price_id"]]
        rows, missing = v2.expand_ganged_sized_attachments_for_quote(window, [board], board_catalog, "offline")
        self.assertEqual(missing, [])
        self.assertEqual([row["attachment_price_id"] for row in rows], [30, 30])
        self.assertGreater(rows[1]["unit_price_override"], rows[0]["matched_price"])
        for row in rows:
            row.update(status="CALCULATED", formula_unit_cost=20, formula_amount=20)
        parent = QWidget()
        parent.refresh_summary = lambda: None
        self.addCleanup(parent.close)
        quote = {"attachments": rows, "ganged_cabinets": window.ganged_cabinets}
        editor = ui.AttachmentEditor(parent, quote)
        self.addCleanup(editor.close)
        self.assertEqual(editor.table.rowCount(), 2)
        self.assertEqual([editor.table.item(index, editor.COL_NAME).text() for index in range(2)],
                         ["柜体1｜安装板", "柜体2｜安装板"])
        editor.show()
        APP.processEvents()
        edits = [(2, 21.25, 310.5), (3, 29.5, 325.75)]
        for index, (quantity, cost, face) in enumerate(edits):
            editor.table.cellWidget(index, editor.COL_QUANTITY).setValue(quantity)
            for column, value in ((editor.COL_UNIT_COST, cost), (editor.COL_UNIT_AMOUNT, face)):
                spin = editor.table.cellWidget(index, column)
                QTest.mouseDClick(spin.lineEdit(), Qt.MouseButton.LeftButton)
                self.assertFalse(spin.lineEdit().isReadOnly())
                spin.setValue(value)
                spin.editingFinished.emit()
        editor.accept()
        saved = json.loads(json.dumps(quote))
        for index, (quantity, cost, face) in enumerate(edits):
            row = saved["attachments"][index]
            self.assertEqual((row["attachment_price_id"], row["ganged_cabinet_index"]), (30, index))
            self.assertEqual(row["item_name"], "安装板")
            self.assertEqual((row["quantity"], row["formula_unit_cost_override"], row["unit_price_override"]),
                             (quantity, cost, face))
            self.assertEqual((row["formula_amount"], row["quick_amount"]), (quantity * cost, quantity * face))
        reopened = ui.AttachmentEditor(parent, saved)
        self.addCleanup(reopened.close)
        for index, values in enumerate(edits):
            self.assertEqual(tuple(reopened.table.cellWidget(index, column).value()
                                   for column in (editor.COL_QUANTITY, editor.COL_UNIT_COST, editor.COL_UNIT_AMOUNT)),
                             values)

    def test_add_to_quote_keeps_child_catalogue_ids_and_request_dimensions(self):
        choices, catalog = fixture()
        namespace = v3_launcher.load_v3_namespace()
        window_class, worker_class = namespace["MainWindow"], namespace["ApiWorker"]
        calculated, failures = [], []

        def catalog_response(worker):
            def respond():
                worker.succeeded.emit({"items": copy.deepcopy(catalog), "data_version": "offline"})
                worker.finished.emit()
            QTimer.singleShot(0, respond)

        with patch.object(window_class, "load_catalogs", lambda _window: None), \
             patch.object(window_class, "refresh_formula_inputs", lambda *_args: None), \
             patch.object(worker_class, "start", catalog_response), \
             patch.object(ui, "_monitor_formula_calculation"):
            window = window_class()
            self.addCleanup(window.close)
            self.assertTrue(layout_refresh._sync_ganged_specification(window, "(800+1000)*600*(1800+200)"))
            window.quote_spec_edit.setText("(800+1000)*600*(1800+200)")
            window.selected_product_code = lambda: "JP"
            window.attachments = choices
            window.show_error = failures.append
            window.calculate = lambda: calculated.append(layout_refresh._build_ganged_attachment_payload(window, [{}, {}]))
            ui._calculate_and_add(window)
            deadline = time.monotonic() + 2
            while not calculated and not failures and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.001)

        self.assertEqual(failures, [])
        self.assertEqual(len(calculated), 1)
        rows = window.attachments
        sent = calculated[0]["attachments"]
        popup_item = {"attachments": rows, "ganged_cabinets": window.ganged_cabinets}
        editor = ui.AttachmentEditor(window, popup_item)
        self.addCleanup(editor.close)
        popup_names = [editor.table.item(index, editor.COL_NAME).text() for index in range(editor.table.rowCount())]
        for index, (_, name, height_field, height) in enumerate(FAMILIES, 1):
            pair = [row for row in rows if row["item_name"] == name]
            self.assertEqual([row.get("ganged_cabinet_index") for row in pair], [0, 1], (name, popup_names))
            self.assertEqual([row["attachment_price_id"] for row in pair], [10 * index, 10 * index + 1], name)
            self.assertEqual([row["size_match_target_width_mm"] for row in pair], [800, 1000], name)
            self.assertEqual(final_attachment_quantity({**pair[1], "cost_quantity_manual": True, "quantity": 2}, 3, 2), 6)
            self.assertEqual([text for text in popup_names if text.endswith(f"｜{name}")],
                             [f"柜体1｜{name}", f"柜体2｜{name}"])
            sent_pair = [row for row in sent if row["attachment_price_id"] in {10 * index, 10 * index + 1}]
            self.assertEqual([row["ganged_cabinet_index"] for row in sent_pair], [0, 1], name)
            if height_field:
                self.assertEqual([row["manual_inputs"][height_field] for row in sent_pair], [height, height], name)
        self.assertEqual([row["attachment_price_id"] for row in sent if "ganged_cabinet_index" not in row], [91, 92])
        self.assertEqual(len(popup_names), 18, popup_names)
        self.assertEqual([bool(editor.table.cellWidget(index, editor.COL_UNIT_COST).property("schemeReadOnly"))
                          for index in range(editor.table.rowCount())],
                         ["｜" not in name for name in popup_names])
        self.assertFalse(v2.needs_ganged_sized_attachment_resolution(window))
        with patch.object(window, "refresh_summary"):
            editor.accept()
        self.assertEqual([row["item_name"] for row in popup_item["attachments"]], [row["item_name"] for row in rows])
        reopened = ui.AttachmentEditor(window, popup_item)
        self.addCleanup(reopened.close)
        self.assertEqual([reopened.table.item(index, reopened.COL_NAME).text()
                          for index in range(reopened.table.rowCount())], popup_names)

        board = next(row for row in rows if row["attachment_price_id"] == 31)
        board.update(quantity=2, attachment_price_sign=-1, formula_cost_edited=True, formula_unit_cost_override=50)
        window.ganged_cabinets[1]["width_mm"] = 1050
        resolved, missing = v2.expand_ganged_sized_attachments_for_quote(window, rows, catalog, "offline")
        self.assertEqual(missing, [])
        board = next(row for row in resolved if row["attachment_price_id"] == 31)
        self.assertEqual(board["size_match_target_width_mm"], 1050)
        self.assertEqual(v2.selected_input(board)["attachment_price_sign"], -1)
        self.assertEqual(board["quantity"], 2)
        self.assertEqual(board["formula_unit_cost_override"], 50)

        fixed_bases = [row for row in rows if row["item_name"] == "固定底座"]
        for index, base in enumerate(fixed_bases):
            base.update(quantity=index + 2, cost_quantity_manual=True,
                        formula_cost_edited=True, formula_unit_cost_override=index + 21,
                        custom_amount_edited=True, unit_price_override=index + 31,
                        quick_amount_override=(index + 2) * (index + 31))
        refreshed, missing = v2.expand_ganged_fixed_bases_for_quote(window, fixed_bases, catalog, "offline")
        self.assertEqual(missing, [])
        self.assertEqual([(row["quantity"], row["formula_unit_cost_override"], row["unit_price_override"])
                          for row in refreshed], [(2, 21, 31), (3, 22, 32)])

        window.ganged_cabinets = []
        self.assertTrue(v2.needs_ganged_sized_attachment_resolution(window))
        single, missing = v2.expand_ganged_sized_attachments_for_quote(window, rows, catalog, "offline")
        self.assertEqual(missing, [])
        self.assertEqual(len(single), len(choices))
        self.assertTrue(all("ganged_cabinet_index" not in v2.selected_input(row) for row in single))


if __name__ == "__main__":
    unittest.main()
