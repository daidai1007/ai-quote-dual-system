"""Offline regressions for API amounts versus real quotation-local edits."""
import copy
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from PySide6.QtWidgets import QApplication, QWidget
import scheme2_ui as ui
import attachment_v2_client as v2

app = QApplication.instance() or QApplication([])


class ApiAmounts(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.window.refresh_summary = lambda:None
        self.addCleanup(self.window.close)

    def editor(self, rows, quantity=1):
        item = dict(attachments=copy.deepcopy(rows), quantity=quantity,
                    quick={"attachment_fee":0,"total_cost":100}, formula={"attachment_fee":0,"total_cost":50})
        dialog = ui.AttachmentEditor(self.window, item)
        self.addCleanup(dialog.close)
        return item, dialog

    def test_closing_unpriced_rows_does_not_save_zero_override(self):
        rows = [dict(item_name=name, category_level1=category, quantity=1)
                for category,name in (("安装板","安装板"),("安装附件","并柜件"),("照明灯/行程开关","照明灯220V长款"))]
        item, editor = self.editor(rows)
        editor.accept()
        for row in item["attachments"]:
            self.assertNotIn("quick_amount_override", row)
            self.assertFalse(row["custom_amount_edited"])
        board = item["attachments"][0]
        merged = v2.merge_cost(board,dict(quantity=1,quick_amount=483.46,formula_amount=162.41,
                              status="CALCULATED",size_match_ratio=1,size_match_exact=True))
        self.assertEqual(merged["quick_amount"],483.46)

    def test_old_automatic_zero_is_replaced_by_api_for_every_family(self):
        for name, amount in (("JP控制柜侧板",737.22),("安装板",483.46),("固定立柱",253.16),
                             ("并柜件",60),("绑线条",20),("照明灯220V长款",25)):
            source = dict(item_name=name, quantity=1, quick_amount=0, quick_amount_override=0,
                          unit_price_override=0, custom_amount_edited=False)
            api = dict(item_name=name, quantity=1, status="CALCULATED", formula_amount=162.41,
                       matched_price=amount, face_price=amount, quick_amount=amount,
                       size_match_ratio=1, size_match_exact=True, size_match_original_price=amount)
            before = copy.deepcopy(source)
            with self.subTest(name=name):
                merged = v2.merge_cost(source, api)
                self.assertEqual(merged["quick_amount"], amount)
                self.assertEqual(merged["formula_amount"],162.41)
                self.assertNotIn("quick_amount_override", merged)
                self.assertNotIn("unit_price_override", v2.selected_input(source))
                self.assertEqual(source, before)

    def test_real_manual_amount_including_zero_survives_api_repricing(self):
        for name in ("安装板","并柜件","照明灯220V长款"):
            for amount in (70,0):
                source = dict(item_name=name, quantity=2, custom_amount_edited=True,
                              quick_amount=amount, quick_amount_override=amount, unit_price_override=amount/2)
                api = dict(item_name=name,quantity=2,status="FIXED",formula_amount=20,quick_amount=100)
                with self.subTest(name=name, amount=amount):
                    merged = v2.merge_cost(source,api)
                    self.assertEqual(merged["quick_amount"],amount)
                    self.assertEqual(merged["formula_amount"],20)
                    self.assertEqual(merged["quick_amount_override"],amount)

    def test_ui_manual_edit_stays_single_cabinet_and_reopens(self):
        source = dict(item_name="并柜件",category_level1="安装附件",attachment_price_id=1101,
                      quantity=2,quick_amount=120,formula_amount=62.96,matched_price=60)
        item, editor = self.editor([source], quantity=3)
        self.assertEqual(editor.table.cellWidget(0,editor.COL_AMOUNT).value(),120)
        editor.table.cellWidget(0,editor.COL_AMOUNT).setValue(210)
        editor.accept()
        row = item["attachments"][0]
        self.assertEqual(row["quick_amount_override"],210)
        self.assertTrue(row["custom_amount_edited"])
        row = v2.merge_cost(row,{**source,"quick_amount":120})
        self.assertEqual(row["quick_amount"],210)
        reopened_item = {**item,"attachments":[row]}
        reopened = ui.AttachmentEditor(self.window,reopened_item)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.table.cellWidget(0,reopened.COL_AMOUNT).value(),210)
        reopened.table.cellWidget(0,reopened.COL_AMOUNT).setValue(0)
        reopened.accept()
        zero = reopened_item["attachments"][0]
        self.assertEqual(zero["attachment_price_id"],1101)
        self.assertTrue(zero["custom_amount_edited"])
        self.assertEqual(zero["quick_amount_override"],0)
        self.assertEqual(v2.merge_cost(zero,source)["quick_amount"],0)

    def test_old_zero_popup_uses_existing_api_price_without_claiming_manual_edit(self):
        source = dict(item_name="安装板",category_level1="安装板",quantity=1,attachment_price_id=1008,
                      quick_amount=0,quick_amount_override=0,custom_amount_edited=False,
                      matched_price=483.46155,face_price=483.46155,formula_amount=162.41)
        item, editor = self.editor([source])
        self.assertEqual(editor.table.cellWidget(0,editor.COL_AMOUNT).value(),483.46)
        editor.accept()
        self.assertNotIn("quick_amount_override",item["attachments"][0])
        self.assertFalse(item["attachments"][0]["custom_amount_edited"])
        self.assertEqual(item["attachments"][0]["quick_amount"],483.46)

    def test_generated_size_price_and_changed_quantity_remain_correct(self):
        source = dict(item_name="安装板",quantity=1,quick_amount_override=0,quick_amount=0,
                      custom_amount_edited=False,unit_price_override=110,
                      matched_price=100,size_match_original_price=100,size_match_ratio=1.1)
        api = dict(item_name="安装板",quantity=1,status="CALCULATED",formula_amount=10,quick_amount=100)
        self.assertEqual(v2.merge_cost(source,api)["quick_amount"],110)
        manual = dict(item_name="并柜件",quantity=2,quick_amount_override=70,custom_amount_edited=True)
        api = dict(item_name="并柜件",quantity=3,status="FIXED",formula_amount=30,quick_amount=180)
        self.assertEqual(v2.merge_cost(manual,api)["quick_amount"],105)
        # A genuine API zero has no automatic override and must not be guessed away.
        self.assertEqual(v2.merge_cost(manual,{**api,"status":"PENDING_MANUAL","quick_amount":0})["quick_amount"],0)

    def test_legacy_explicit_nonzero_edit_is_retained(self):
        source = dict(item_name="照明灯220V长款",quantity=1,quick_amount_override=30)
        api = dict(item_name="照明灯220V长款",quantity=1,status="FIXED",formula_amount=8.5,quick_amount=25)
        self.assertEqual(v2.merge_cost(source,api)["quick_amount"],30)

    def test_genuine_api_zero_and_custom_cost_link_stay_valid(self):
        source = dict(item_name="零价附件",quantity=1,quick_amount=0,matched_price=25,formula_amount=10)
        self.assertEqual(ui.AttachmentEditor._display_amounts(source),(10,0))
        source = dict(item_name="临时附件",custom=True,quantity=1,formula_amount=10,quick_amount=12)
        item, editor = self.editor([source])
        editor.table.cellWidget(0,editor.COL_FORMULA_AMOUNT).setValue(20)
        self.assertEqual(editor.table.cellWidget(0,editor.COL_AMOUNT).value(),24)
        editor.table.cellWidget(0,editor.COL_AMOUNT).setValue(30)
        editor.table.cellWidget(0,editor.COL_FORMULA_AMOUNT).setValue(25)
        self.assertEqual(editor.table.cellWidget(0,editor.COL_AMOUNT).value(),30)
        editor.accept()
        self.assertEqual(item["attachments"][0]["quick_amount"],30)


if __name__ == "__main__":
    unittest.main()
