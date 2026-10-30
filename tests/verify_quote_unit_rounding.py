"""Cent rounding through real cost/quote tables, print HTML and export snapshots."""
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidget
import layout_refresh
import scheme2_ui
from quick_discount_rules import PRICING_BASIS, money, money_sum, money_product, quick_order_line_breakdown, apply_management_fee

CASES = json.loads((ROOT / "tests/fixtures/quote_unit_rounding.json").read_text(encoding="utf-8"))
APP = QApplication.instance() or QApplication([])


def expected_formula_unit(sample):
    management = money_product(money_sum((sample["base"], sample.get("eligible", 0),
                                          sample.get("original", 0), sample["freight"])), .06)
    return money_sum((money_product(money_sum((sample["base"], management, sample.get("eligible", 0))),
                                    sample["discount"]), sample.get("original", 0), sample["freight"]))


def quote_item(sample):
    attachments = []
    for field, name in (("eligible", "安装板"), ("original", "其他附件")):
        if sample.get(field):
            attachments.append(dict(item_name=name, category_level1=name, quantity=1,
                                    quick_amount=sample[field], formula_amount=sample[field]))
    fee = money(sum(row["quick_amount"] for row in attachments))
    item = dict(
        name=sample["name"], product_code="JS_SINGLE", material_code="SECC",
        specification="1000*600*2000", quantity=sample["quantity"],
        quick_discount=sample["discount"], formula_discount=sample["discount"],
        freight_fee=sample["freight"], ganged_cabinet_count=sample.get("ganged", 1),
        # Complete persisted manual-remark fields avoid triggering the legacy
        # remark migration during a test whose contract is monetary immutability.
        attachments=attachments, final_remark="保留备注。", quote_remark_manual=True,
        notes="保留备注。", source_ocr_remark="保留备注。", source_reviewed_remark="保留备注。",
        quick=dict(base_price=sample["base"], attachment_fee=fee, total_cost=money(sample["base"] + fee)),
        formula=dict(material_cost=sample["base"], auxiliary_cost=0, labor_cost=0,
                     spray_cost=0, management_fee=0, attachment_fee=fee,
                     total_cost=money(sample["base"] + fee)),
    )
    item["formula"] = apply_management_fee(item["formula"], item["freight_fee"])
    return item


class QuoteUnitRounding(unittest.TestCase):
    def test_tables_print_and_export_snapshot_share_cent_rounded_unit_price(self):
        for sample in CASES:
            with self.subTest(case=sample["name"]):
                item = quote_item(sample)
                before = deepcopy(item)
                window = SimpleNamespace(
                    # These are recorded legacy costs; an editable new quote
                    # intentionally opts into manufacture4/management5.
                    _quote_scheme_read_only=True,
                    draft_items=[item], summary_table=QTableWidget(0, len(scheme2_ui.HEADERS)),
                    scheme2_quote_preview=QTableWidget(0, 8),
                    scheme2_company=SimpleNamespace(currentText=lambda: "测试公司"),
                    scheme2_order_number=QLineEdit(),
                )
                scheme2_ui._refresh_cost_table(window)
                scheme2_ui._refresh_quote_page(window)
                expected_unit = f'{sample["unit"]:,.2f}'
                expected_total = f'{sample["total"]:,.2f}'
                self.assertEqual(window.summary_table.item(0, 10).text(), expected_unit)
                self.assertEqual(window.summary_table.item(0, 11).text(), expected_total)
                self.assertEqual(window.scheme2_quote_preview.item(10, 5).text(), expected_unit)
                self.assertEqual(window.scheme2_quote_preview.item(10, 6).text(), expected_total)
                printed = scheme2_ui._printable_quote_html(window)
                self.assertIn(f"<td>{expected_unit}</td><td>{expected_total}</td>", printed)
                exported = scheme2_ui._quote_export_items_snapshot(window)[0]
                self.assertEqual(exported["pricing_basis"], PRICING_BASIS)
                self.assertEqual(exported["ganged_cabinet_count"], sample.get("ganged", 1))
                self.assertEqual(exported["quick"]["base_price"], sample["base"])
                self.assertEqual(exported["quote_display"]["unit_price"], sample["unit"])
                self.assertEqual(exported["quote_display"]["total"], sample["total"])
                self.assertEqual(Decimal(str(sample["unit"])) * sample["quantity"],
                                 Decimal(str(sample["total"])))
                formula = layout_refresh._formula_order_line_breakdown(item)
                self.assertEqual(formula["equivalent_unit_total"], expected_formula_unit(sample))
                self.assertEqual(formula["line_total"], money_product(expected_formula_unit(sample), sample["quantity"]))
                self.assertEqual(item, before, "Displaying or exporting must not mutate stored costs")

    def test_freight_stays_outside_every_discount_and_quantity(self):
        for quantity in (1, 3, 10):
            for discount in (0.1, 0.75, 1):
                for ganged in (1, 2):
                    with self.subTest(quantity=quantity, discount=discount, ganged=ganged):
                        item = quote_item(dict(name="运费", base=1234.55, discount=discount,
                                               quantity=quantity, freight=36.67, ganged=ganged))
                        zero = quick_order_line_breakdown(item["quick"], [], discount, quantity, ganged, 0)
                        freight = quick_order_line_breakdown(item["quick"], [], discount, quantity, ganged, 36.67)
                        self.assertEqual(Decimal(str(freight["equivalent_unit_total"]))
                                         - Decimal(str(zero["equivalent_unit_total"])), Decimal("36.67"))
                        self.assertEqual(Decimal(str(freight["line_total"]))
                                         - Decimal(str(zero["line_total"])), Decimal("36.67") * quantity)
                        self.assertEqual(layout_refresh._formula_order_line_breakdown(item)["line_total"],
                                         money_product(expected_formula_unit(dict(base=1234.55,discount=discount,freight=36.67)), quantity))

    def test_manually_edited_unit_price_rounds_before_quantity(self):
        item = quote_item(dict(name="人工单价", base=1000, discount=1, quantity=3, freight=0))
        window = SimpleNamespace(draft_items=[item], scheme2_quote_preview=QTableWidget(0, 8),
                                 scheme2_company=SimpleNamespace(currentText=lambda: ""),
                                 scheme2_order_number=QLineEdit())
        window.refresh_summary = lambda: scheme2_ui._refresh_quote_page(window)
        scheme2_ui._refresh_quote_page(window)
        window.scheme2_quote_preview.item(10, 5).setText("123.455")
        scheme2_ui._quote_unit_price_changed(window, 10, 5)
        self.assertEqual(window.scheme2_quote_preview.item(10, 5).text(), "123.46")
        self.assertEqual(window.scheme2_quote_preview.item(10, 6).text(), "370.38")


if __name__ == "__main__":
    unittest.main()
