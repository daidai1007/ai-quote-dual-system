"""JC identity/amounts through real Qt save, JSON reopen and Node export.

The save transport is the existing in-memory scheme fixture. No sockets or
existing databases are used, and the generated workbook contains synthetic data.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import layout_refresh
import verify_weight_freight as fixture
from verify_quote_document_progress import app, wait, ui
from verify_quote_export_customer import workbook_cell
import quote_scheme_center as schemes

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT/'tests/fixtures/jc_profiles.json').read_text(encoding='utf-8'))


class JcRoundtrip(unittest.TestCase):
    def setUp(self):
        self.h = fixture.WeightFreight()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.w = self.h.w
        self.w.request_history_match = lambda *_: None
        history = patch.object(layout_refresh, '_request_history_price_match', lambda *_: None)
        history.start()
        self.addCleanup(history.stop)
        self.w.product_catalog_loaded({'items': [{
            'product_code': 'JC_EXP', 'product_name': 'JC', 'product_method': 'experience',
            'default_width_mm': 600, 'default_height_mm': 1600, 'default_depth_mm': 600,
            'models': [{'model_code': row['model']} for row in CASES]}]})

    def test_save_json_reopen_and_real_excel_keep_all_four_model_profiles(self):
        w = self.w
        rows = []
        for index, case in enumerate(CASES):
            w.product_combo.setCurrentIndex(w.product_combo.findData(case['label']))
            row = deepcopy(self.h.item)
            row.update(name=case['label'], product_family=case['label'], product_code='JC_EXP',
                       variant_code=case['profile'], variant_name=case['label'], model_code=case['model'],
                       width_mm=600, height_mm=1600, depth_mm=case['depth'],
                       specification=f"600*{case['depth']}*1600", quantity=2, quick_discount=.5,
                       freight_mode='MANUAL', freight_fee=12, attachments=[],
                       quick=dict(base_price=(index+1)*1000, attachment_fee=0, total_cost=(index+1)*1000),
                       formula=dict(material_cost=100, auxiliary_cost=10, labor_cost=20,
                                    spray_cost=30, attachment_fee=0, management_fee=10, total_cost=170))
            row.pop('quote_display', None)
            ui._stamp_selected_product(w, row)
            rows.append(row)
        w.draft_items = rows
        w.quote_management.latest_workspace = None
        w.quote_management.history_version = None
        w._qm_state = {}
        w._quote_scheme_loading = False
        w.refresh_summary()
        w._quote_scheme_save_timer.stop()
        before = [(r['variant_code'], r['model_code'], ui._row_values(r)[15:19]) for r in rows]
        w.quote_management.save()
        wait(lambda:w._quote_scheme_save_worker is None and not w._quote_scheme_workers)
        puts = [r for r in self.h.scheme_requests if r[0] == 'PUT']
        self.assertTrue(puts, 'The real save controller must emit a PUT snapshot')
        # Exercise the actual serialization boundary rather than deepcopy alone.
        saved = json.loads(json.dumps(self.h.server, ensure_ascii=False))
        self.assertEqual([r['variant_code'] for r in saved['snapshot']['draft_items']],
                         [r['profile'] for r in CASES])
        w.draft_items = []
        schemes._apply_opened_scheme(w, saved, ui.COST_ROUTE)
        w._quote_scheme_save_timer.stop()
        after = [(r['variant_code'], r['model_code'], ui._row_values(r)[15:19]) for r in w.draft_items]
        self.assertEqual(after, before)
        for row, case in zip(w.draft_items, CASES):
            frozen = deepcopy(row)
            w.load_draft_item(row)
            self.assertEqual(w.product_combo.currentData(), case['label'])
            self.assertEqual(w.selected_variant_code(), case['profile'])
            self.assertEqual(row, frozen, 'Opening an item must not rewrite saved money')
        w.show_section(ui.QUOTE_ROUTE)
        self.h.export()
        self.assertTrue(self.h.path.is_file())
        for index, (row, case, expected) in enumerate(zip(w.draft_items, CASES, before), 11):
            self.assertEqual(workbook_cell(self.h.path, '报价', f'B{index}'), case['label'])
            self.assertEqual(float(workbook_cell(self.h.path, '报价', f'F{index}')), expected[2][0])
            self.assertEqual(float(workbook_cell(self.h.path, '报价', f'G{index}')), expected[2][1])
            self.assertEqual(float(workbook_cell(self.h.path, '成本', f'F{index}')), expected[2][2])
            self.assertEqual(float(workbook_cell(self.h.path, '成本', f'G{index}')), expected[2][3])
        self.assertEqual([r['variant_code'] for r in self.h.posts()[-1]['snapshot']['draft_items']],
                         [r['profile'] for r in CASES])
        if output := os.environ.get('AI_QUOTE_JC_QA_OUTPUT'):
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.h.path, target/'jc-four-model-roundtrip.xlsx')
            (target/'jc-four-model-roundtrip.json').write_text(json.dumps(
                dict(saved_snapshot=saved, expected_prices_and_costs=before,
                     scope='Synthetic rows; in-memory save transport; no business database'),
                ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
