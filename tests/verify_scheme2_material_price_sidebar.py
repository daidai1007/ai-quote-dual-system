"""Eight permanent coefficients in the actual recovered Qt workbench."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QScrollArea
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
import scheme2_ui as ui
import layout_refresh
import v3_launcher
from material_prices import material_unit_price, migrate_material_prices

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
ns["install_application_font"](app)
ns["MainWindow"].load_catalogs = lambda self: None
ns["AttachmentDialog"].load_catalog = lambda self, *_args: None
window = ns["MainWindow"]()
window.refresh_summary = lambda: ui._refresh_cost_table(window)
expected = ["镀锌板价格", "碳钢价格", "不锈钢304价格", "不锈钢316价格",
            "材料差价价格", "废料系数", "人工折扣", "表面处理价格"]
assert [label for _key, label, *_rest in ui.COEFFICIENT_FIELDS] == expected
assert len(window.scheme2_cost_controls) == 8


def sample(code, legacy_price=None):
    price = {"SECC": 4.2, "SUS304": 16.0, "SUS316": 32.4}[code]
    settings = {"stainless_price": legacy_price} if legacy_price is not None else {}
    parts = [{"part_name": "箱体", "material_code": code, "billable_weight_kg": 10,
              "material_unit_price": price, "material_cost": price * 10},
             {"part_name": "安装板", "material_code": "SGCC", "billable_weight_kg": 2,
              "material_unit_price": 4.55, "material_cost": 9.1}]
    return {"material_code": code, "quantity": 1, "product_code": "JA", "scheme2_cost_settings": settings,
            "formula": {"material_cost": price * 10 + 9.1, "total_cost": price * 10 + 109.1,
                        "corrected_material_weight_kg": 12, "material_details": deepcopy(parts),
                        "cabinet_material_part_details": deepcopy(parts)}, "quick": {"total_cost": 1000}}


try:
    window.resize(1519, 987)
    window.show()
    window.show_section(ui.COST_ROUTE)
    QTest.qWait(50)
    ui._sync_sidebar(window)
    assert not window.scheme2_cost_sidebar.isHidden()
    assert all(not field.isHidden() for field in window.scheme2_cost_fields.values())
    window.draft_items = [sample("SECC"), sample("SUS304", 17.5), sample("SUS316", 35)]
    ui._refresh_cost_table(window)
    for index in range(3):
        window.summary_table.selectRow(index)
        ui._sync_sidebar(window)
        assert [field.findChild(QLabel, "scheme2FieldLabel").text()
                for field in window.scheme2_cost_fields.values()] == expected
        assert all(not field.isHidden() for field in window.scheme2_cost_fields.values())
    assert window.draft_items[1]["scheme2_cost_settings"]["stainless_304_price"] == 17.5
    assert window.draft_items[1]["scheme2_cost_settings"]["stainless_316_price"] == 32.4
    assert window.draft_items[2]["scheme2_cost_settings"]["stainless_316_price"] == 35
    assert window.draft_items[2]["scheme2_cost_settings"]["stainless_304_price"] == 16
    window.summary_table.selectRow(1)
    ui._apply_cost_control(window, "stainless_316_price", 40)
    assert window.draft_items[1]["formula"]["material_cost"] == 184.1
    control = window.scheme2_cost_controls["stainless_304_price"]
    control.setValue(20)
    control.editingFinished.emit()
    item = window.draft_items[1]
    assert item["formula"]["material_cost"] == 209.1
    assert ui._detail_rows(item)[0]["unit_price"] == 20
    assert item["scheme2_cost_settings"]["stainless_316_price"] == 40
    window.summary_table.selectRow(2)
    ui._apply_cost_control(window, "stainless_316_price", 36)
    item316 = window.draft_items[2]
    assert item316["formula"]["material_cost"] == 369.1
    ui._apply_cost_control(window, "material_difference", 30)
    assert ui._material_difference_amount(item316) == 300
    assert ui._material_difference_amount(item) == 0

    # Actual worker wrapper sends the grade-specific price to the single API.
    sent = []
    class Response:
        headers = {"Content-Type": "application/json"}
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return b'{"formula_cost":{},"quick_quote":{}}'
    def urlopen(request, **_kwargs):
        sent.append(json.loads(request.data))
        return Response()
    original_open = layout_refresh.urllib.request.urlopen
    layout_refresh.urllib.request.urlopen = urlopen
    try:
        for code, price in (("SUS304", 20), ("SUS316", 40)):
            window._scheme2_active_settings = item["scheme2_cost_settings"]
            worker = ns["ApiWorker"]("https://quote.test/api/quotes/calculate-dual", {"material_code": code}, window)
            failures = []
            worker.failed.connect(failures.append)
            worker.run()
            assert not failures, failures
            assert sent[-1]["material_unit_price_override"] == price
            worker.deleteLater()
        window._scheme2_active_settings = None
        window.scheme2_defaults["stainless_316_price"] = 42
        worker = ns["ApiWorker"]("https://quote.test/api/quotes/calculate-dual", {"material_code": "SUS316"}, window)
        worker.run()
        assert sent[-1]["material_unit_price_override"] == 42
        window.scheme2_defaults["stainless_316_price"] = 32.4
        worker.deleteLater()
    finally:
        layout_refresh.urllib.request.urlopen = original_open
        window._scheme2_active_settings = None

    combo = lambda value: SimpleNamespace(currentData=lambda: value)
    ganged = SimpleNamespace(
        ganged_cabinets=[{"width_mm": width, "height_mm": 2100, "depth_mm": 600,
                         "single_door_count": 1, "double_door_count": 0} for width in (1000, 800)],
        product_combo=combo("JP"), product_catalog={"JP": {"codes": {"SINGLE": "JP_SINGLE"}}},
        coating_combo=combo("无"), material_combo=combo("SUS316"), quote_date=None,
        formula_calculator=SimpleNamespace(calculate=lambda *_args: (10, 1)),
        scheme2_defaults=item["scheme2_cost_settings"])
    payloads, *_metrics = layout_refresh._build_ganged_quote_payloads(ganged)
    assert [payload["material_unit_price_override"] for payload in payloads] == [40, 40]
    for width, height, name in ((1519, 987, "wide"), (1024, 700, "compact")):
        window.resize(width, height)
        QTest.qWait(50)
        ui._apply_responsive(window)
        assert not window.scheme2_cost_sidebar.isHidden()
        assert window.scheme2_compact_coefficients.isHidden()
        assert all(not field.isHidden() for field in window.scheme2_cost_fields.values())
        for field in window.scheme2_cost_fields.values():
            label = field.findChild(QLabel, "scheme2FieldLabel")
            assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width(), label.text()
        viewport = window.scheme2_cost_sidebar.findChild(QScrollArea).viewport()
        for control in window.scheme2_cost_controls.values():
            assert control.mapTo(viewport, control.rect().topRight()).x() < viewport.width()
        output = ROOT / "outputs" / "coefficient-sidebar-verification"
        output.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(output / f"{name}.png"))
    child = sample("SUS304")["formula"]
    gang = {"material_code": "SUS304", "scheme2_cost_settings": window.scheme2_defaults.copy(),
            "formula": {"material_cost": 338.2, "total_cost": 538.2,
                        "ganged_cabinet_costs": [{"cabinet_index": i, "formula_cost": deepcopy(child)} for i in (1, 2)]}}
    table = QTableWidget(1, 1)
    table.setCurrentCell(0, 0)
    model = SimpleNamespace(summary_table=table, draft_items=[gang], scheme2_defaults=window.scheme2_defaults,
                            refresh_summary=lambda: None)
    ui._apply_cost_control(model, "stainless_304_price", 20)
    assert gang["formula"]["material_cost"] == 418.2
    assert [row["unit_price"] for row in ui._detail_rows(gang) if row.get("name") == "箱体"] == [20, 20]
    assert material_unit_price(migrate_material_prices({"stainless_price": 38}, "SUS316"), "SUS304") == 16
    print("PASS: eight permanent fields, independent 304/316 prices, legacy migration, detail costs, API payloads and responsive Qt layout")
finally:
    window.close()
