"""Offline Qt contract using responses produced by the local PostgreSQL service test.

No production API is contacted. Run once with --source and once with the V3 core.
"""
import copy
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtCore import QTimer, Qt, QDate
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QLineEdit, QInputDialog

if "--source" in sys.argv:
    import main
    ns = vars(main)
    mode = "source"
else:
    import v3_launcher
    ns = v3_launcher.load_v3_namespace()
    mode = "v3"

from attachment_v2_client import selected_input, environment
fixture = json.loads((ROOT / "test-output/attachment-cost-v2/api-client-fixtures.json").read_text(encoding="utf-8"))
app = QApplication.instance() or QApplication([])
if "install_application_font" in ns:
    ns["install_application_font"](app)
else:
    from PySide6.QtGui import QFont, QFontDatabase
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
Window, Dialog, Worker = (ns[key] for key in ("MainWindow", "AttachmentDialog", "ApiWorker"))
Window.load_catalogs = lambda self: None
Window.refresh_formula_inputs = lambda self, *args: None
requests = []
messages = []
QMessageBox.information = lambda *args: messages.append(args[2])
QMessageBox.warning = lambda *args: messages.append(args[2])
missing_id = fixture["missing"]["attachments"][0]["attachment_price_id"]
costs = {a["attachment_price_id"]: a for a in fixture["complete"]["attachments"]}
costs[missing_id] = fixture["missing"]["attachments"][0]
catalog = {**fixture["catalog"], "items": [a for a in fixture["catalog"]["items"] if a["attachment_price_id"] in costs]}

# Exercise the real ApiWorker constructor/payload adapter. Replace only network I/O.
original_worker_init = Worker.__init__
def capture_init(self, url, payload, parent=None, *args, **kwargs):
    original_worker_init(self, url, payload, parent, *args, **kwargs)
    self.test_url = url
    self.test_payload = copy.deepcopy(self.payload)
Worker.__init__ = capture_init
def start(self):
    requests.append((self.test_url, self.test_payload))
    def respond():
        if "catalog?v=2" in self.test_url:
            body = catalog
        elif self.test_url.endswith("/preview"):
            rows = []
            for chosen in self.test_payload["attachments"]:
                row = copy.deepcopy(costs[chosen["attachment_price_id"]])
                if chosen["attachment_price_id"] == missing_id and chosen["manual_inputs"].get("底座高度"):
                    row = copy.deepcopy(fixture["manualComplete"]["attachments"][0])
                row.update(manual_inputs=chosen["manual_inputs"], quantity=chosen["quantity"])
                row["quick_amount"] = round(row["face_price"] * chosen["quantity"] * chosen["attachment_price_sign"], 2)
                if row.get("formula_unit_cost") is not None:
                    row["formula_amount"] = round(row["formula_unit_cost"] * chosen["quantity"] * chosen["attachment_price_sign"], 2)
                rows.append(row)
            body = {"attachments": rows, "errors": [r for r in rows if r["status"] == "ERROR"]}
        else:
            body = {**fixture["result"], "quote_id": self.test_payload.get("quote_id")}
        self.succeeded.emit(body)
        self.finished.emit()
    QTimer.singleShot(15, respond)
Worker.start = start
def spin_until(predicate, message):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message + " urls=" + repr([r[0] for r in requests[-3:]]) + " messages=" + repr(messages) + " risk=" + window.risk_label.text())

window = Window()
window.api_url.setText("http://127.0.0.1:1/api/quotes/calculate-dual")
window.selected_product_code = lambda: "JP"
window.product_catalog = {"JP": {"method": "quick", "codes": {"DEFAULT": "JP"}}}
window.product_combo.blockSignals(True)
window.product_combo.addItem("JP", "JP")
window.product_combo.setCurrentIndex(window.product_combo.findData("JP"))
window.product_combo.blockSignals(False)
if hasattr(window, "quote_spec_edit"):
    window.quote_spec_edit.setText("800*600*2000")
window.width_spin.setValue(800)
window.height_spin.setValue(2000)
window.depth_spin.setValue(600)
window.quantity_spin.setValue(1)
window.quote_date.setDate(QDate(2026, 9, 11))
window.material_combo.setCurrentIndex(window.material_combo.findData("SECC"))
window.coating_combo.setCurrentIndex(window.coating_combo.findData("橘纹"))
window.attachments = []
dialog = Dialog([], window.api_url.text(), window, target_dimensions=(800,2000,600))
dialog.show()
spin_until(lambda: len(dialog.catalog) == len(catalog["items"]), "catalog did not load")
assert dialog._v2_mode and dialog.table.columnCount() == 11
rows = {}
for row in range(dialog.table.rowCount()):
    cell = dialog.table.item(row, dialog.COL_CHECK)
    source = cell.data(Qt.UserRole)
    rows[source["attachment_price_id"]] = row
    cell.setCheckState(Qt.Checked)
    # Exact catalogue face remains readonly, including all Excel decimal places.
    assert not dialog.table.item(row, dialog.COL_PRICE).flags() & Qt.ItemIsEditable
spin_until(lambda: any("底座高度" in (dialog.table.item(row, 7).text()) for row in rows.values()), "manual error was not shown")
assert not dialog._v2_ready
dialog.accept_selection()
assert messages and "计算完成" in messages[-1]

# Edit through the actual dimension dialog; blanks are not converted to zero.
original_exec = QDialog.exec
def edit_exec(self):
    for field in self.findChildren(QLineEdit):
        assert field.text() == ""
        field.setText("100")
    return QDialog.Accepted
QDialog.exec = edit_exec
dialog.table.cellDoubleClicked.emit(rows[missing_id], 10)
QDialog.exec = original_exec
spin_until(lambda: dialog._v2_ready, "manual dimension did not unblock preview")
collected = dialog.collect_attachments()
manual_row = next(a for a in collected if a["attachment_price_id"] == missing_id)
assert manual_row["manual_inputs"]["底座高度"] == "100"
assert all("unit_price_override" not in a for a in collected)
assert any(a.get("status") == "QUICK_ONLY" for a in collected)
assert any(a.get("auxiliary_list") for a in collected)
dialog.table.item(rows[missing_id], dialog.COL_QUANTITY).setText("2")
spin_until(lambda: dialog._v2_ready, "quantity change did not recalculate")
manual_row = next(a for a in dialog.collect_attachments() if a["attachment_price_id"] == missing_id)
assert manual_row["quantity"] == 2 and manual_row["manual_inputs"]["底座高度"] == "100"
assert not manual_row.get("error"), "stale error survived a successful calculation"
for identifier, row in rows.items():
    expected = next(a["price"] for a in catalog["items"] if a["attachment_price_id"] == identifier)
    assert float(dialog.table.item(row, dialog.COL_PRICE).text()) == expected
identity = catalog["items"][0]
assert not Dialog._same_catalog_choice(identity, {**identity, "attachment_price_id": -999, "category_level1": "其他分类"})
assert Dialog._same_catalog_choice(identity, identity)

# Render the new columns and original multiline auxiliary text for review.
dialog.category_selection = []
dialog.search_edit.setText("")
getattr(dialog, "category_panel", getattr(dialog, "attachment_category_panel", None)).hide()
dialog.table.show()
for row in rows.values():
    dialog.table.setRowHidden(row, False)
app.processEvents()
dialog.table.scrollToItem(dialog.table.item(0, 10))
app.processEvents()
dialog.grab().save(str(ROOT / f"test-output/attachment-cost-v2/client-{mode}-attachment.png"))
dialog.close()

# Real show/add/reopen keeps the server row/selection IDs and immutable costs.
window.attachments = copy.deepcopy(fixture["result"]["attachments"])
window.weight_edit.setText("10")
window.area_edit.setText("2")
window.calculate()
spin_until(lambda: window.current_result is not None, "single cabinet response rejected")
sent = next(payload for url, payload in reversed(requests) if url.endswith("/calculate-dual"))
assert sent["attachment_contract"] == 2
assert set(sent["attachments"][0]) == {"attachment_price_id", "quantity", "attachment_price_sign", "manual_inputs"}
assert window.current_result["formula"]["attachment_fee"] == 12
assert window.current_result["quick"]["attachment_fee"] == 40
window.add_current_to_summary()
item = window.draft_items[-1]
assert item["attachment_contract"] == 2 and item["quote_line_id"] == fixture["result"]["quote_line_id"]
window.load_draft_item(item)
assert window._attachment_v2_line_id == item["quote_line_id"]
assert window.attachments[0]["attachment_selection_id"] == fixture["result"]["attachments"][0]["attachment_selection_id"]
window.width_spin.setValue(801)
assert window.current_result is None and window._attachment_v2_line_id is None
window.show_result({**fixture["result"], "quote_id": sent["quote_id"]})
assert window.current_result is None, "old response was accepted after the dimensions changed"
spin_until(lambda: getattr(window, "_v2_environment_worker", None) is None and not window._v2_environment_timer.isActive(), "environment preview did not finish")

# An error response cannot leave a usable old formula total or enter the draft.
before = len(window.draft_items)
error_result = {**fixture["result"], "attachments": fixture["missing"]["attachments"], "formula_cost": {"total_cost": None,"attachment_fee":None}}
window._v2_request_environment = None
window.current_result = {"formula": error_result["formula_cost"], "quick": error_result["quick_quote"]}
window.attachments = error_result["attachments"]
window.refresh_discounted_totals()
assert window.current_result["formula"]["total_cost"] is None
window.add_current_to_summary()
assert len(window.draft_items) == before

# The unchanged ganged calculation cannot accidentally consume V2 amounts.
window.ganged_cabinet_count = 2
window.ganged_cabinets = [{"width_mm":400}, {"width_mm":400}]
before = len(requests)
window.calculate()
assert len(requests) == before and "并柜" in messages[-1]
window.close()
app.processEvents()
print(f"PASS {mode}: V2 catalog, exact IDs, manual dimensions, dual amounts, snapshot reopen, invalidation, ERROR and ganged gate")
