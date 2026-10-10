"""Actual V3 export/confirm transport plus the real API snapshot guard, offline."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import verify_drawing_workflow as base
from attachment_v2_client import confirmation_inputs, confirmation_payload

ROOT = Path(__file__).resolve().parents[1]


class ExportSnapshotTests(unittest.TestCase):
    setUp = base.DrawingWorkflowTests.setUp
    tearDown = base.DrawingWorkflowTests.tearDown
    accept = base.DrawingWorkflowTests.accept

    def payload(self):
        payload = json.loads((ROOT / 'tests/fixtures/export_formula_cost_detail.json').read_text('utf-8'))
        item = payload['items'][0]
        item.update(name='并柜回归', attachment_contract=2,
                    quote_line_id='12345678-1234-1234-1234-123456789001', quantity=3,
                    ganged_cabinet_count=2, ganged_cabinets=[
                        {'width_mm': 1000, 'depth_mm': 600, 'height_mm': 2100, 'base_height_mm': 100},
                        {'width_mm': 800, 'depth_mm': 600, 'height_mm': 2100, 'base_height_mm': 100}])
        item['attachments'] = [dict(item_name='固定底座 柜体' + str(i + 1),
                                    attachment_price_id=101 + i, quantity=3,
                                    attachment_price_sign=1, ganged_cabinet_index=i,
                                    manual_inputs={'宽度': width, '深度': 600, '底座高度': 100},
                                    catalog_version='offline', status='FIXED',
                                    formula_unit_cost=5, formula_amount=15,
                                    face_price=10, quick_amount=30, unit='件')
                               for i, width in enumerate((1000, 800))]
        item['attachment_confirmation_inputs'] = confirmation_inputs(item['attachments'])
        for row in item['attachment_confirmation_inputs']:
            row['quantity'] = 1  # UI displays 3; API snapshot remains per cabinet.
        item['attachments'].append(dict(custom=True, item_name='木托', name='木托',
                                         quantity=1, attachment_price_sign=1,
                                         unit_price_override=10, quick_amount=10,
                                         formula_amount=5))
        other = copy.deepcopy(item)
        other.update(name='单柜回归', quantity=2,
                     quote_line_id='12345678-1234-1234-1234-123456789002',
                     ganged_cabinet_count=1, ganged_cabinets=[])
        other['attachments'] = []
        other['attachment_confirmation_inputs'] = []
        payload['items'] = [item, other]
        return payload

    def node(self, args, value=None):
        result = subprocess.run(['node', *args], cwd=ROOT,
                                input=json.dumps(value, ensure_ascii=False) if value is not None else None,
                                capture_output=True, text=True, encoding='utf-8',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_excel_and_both_confirmation_requests_use_identical_snapshot(self):
        payload = self.payload()
        unchanged = copy.deepcopy(payload)
        expected = confirmation_payload(payload, validate=True)
        for endpoint in ('confirm', 'confirm-check'):
            worker = base.ns['ApiWorker']('https://offline.invalid/api/quotes/' + endpoint, payload, self.w)
            self.assertEqual(worker.payload, expected)
        snapshots = {}
        for item in expected['items']:
            environment = {key: item.get(key) for key in (
                'product_code', 'material_code', 'width_mm', 'height_mm', 'depth_mm',
                'coating_type', 'quote_date', 'cabinet_body_thickness_mm', 'waste_factor',
                'ganged_cabinet_count', 'ganged_cabinets')}
            environment['quote_result'] = dict(formula_cost=item['formula'], quick_quote=item['quick'])
            saved_rows = []
            for index, selection in enumerate(item['attachment_confirmation_inputs']):
                saved_rows.append({**item['attachments'][index], **selection,
                                   'attachment_selection_id': index + 1,
                                   'quote_line_id': item['quote_line_id'],
                                   'formula_amount': 5, 'quick_amount': 10})
            snapshots[item['quote_line_id']] = dict(environment=environment, attachments=saved_rows)
        hydrated = json.loads(self.node(['tests/attachment_export_snapshot_bridge.mjs'],
                                        dict(payload=expected, snapshots=snapshots)))
        self.assertEqual(hydrated['items'][0]['attachments'][-1]['custom'], True)
        self.assertEqual(hydrated['items'][0]['attachments'][-1]['formula_amount'], 5)
        self.assertEqual(hydrated['items'][0]['formula']['total_cost'], expected['items'][0]['formula']['total_cost'] + 5)
        self.assertEqual(hydrated['items'][0]['quick']['total_cost'], expected['items'][0]['quick']['total_cost'] + 10)
        self.assertEqual([r['ganged_cabinet_index'] for r in hydrated['items'][0]['attachments'][:2]], [0, 1])
        with tempfile.TemporaryDirectory(dir=ROOT / 'outputs', prefix='export-snapshot-') as directory:
            directory = Path(directory)
            source, server, output = [directory / name for name in ('input.json', 'server.xlsx', 'client.xlsx')]
            source.write_text(json.dumps(hydrated, ensure_ascii=False), 'utf-8')
            self.node(['export_dual_quote_workbook.mjs', str(source), str(server)])
            response = base.Mock()
            response.__enter__ = lambda _: response
            response.__exit__ = lambda *args: None
            response.read.return_value = server.read_bytes()
            with patch('urllib.request.urlopen', return_value=response) as transport:
                self.w.export_workbook(str(output), payload)
            request = transport.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/api/quotes/export'))
            self.assertEqual(json.loads(request.data), expected)
            with ZipFile(output) as workbook:
                self.assertIsNone(workbook.testzip())
                self.assertIn('xl/worksheets/sheet1.xml', workbook.namelist())
        self.assertEqual(payload, unchanged)

    def test_saved_catalogue_ids_custom_flags_and_frozen_inputs_survive_real_summary(self):
        item = self.payload()['items'][0]
        self.w.width_spin.setValue(1000)
        self.w.depth_spin.setValue(600)
        self.w.height_spin.setValue(2100)
        self.w.quote_spec_edit.setText('1000*600*2100')
        self.w.quantity_spin.setValue(3)
        self.w.attachments = copy.deepcopy(item['attachments'])
        self.accept(base.response())
        self.w._attachment_v2_line_id = item['quote_line_id']
        self.w._v2_confirmation_inputs = copy.deepcopy(item['attachment_confirmation_inputs'])
        with patch.object(base.QMessageBox, 'warning') as warning, patch.object(base.QMessageBox, 'information') as information:
            self.w.add_current_to_summary()
        self.assertEqual(len(self.w.draft_items), 1, repr((warning.call_args, information.call_args)))
        saved = self.w.draft_items[0]
        self.assertEqual([r.get('attachment_price_id') for r in saved['attachments'][:2]], [101, 102])
        self.assertTrue(saved['attachments'][-1]['custom'])
        self.assertEqual(saved['attachments'][-1]['item_name'], '木托')
        self.assertEqual(saved['attachment_confirmation_inputs'], item['attachment_confirmation_inputs'])
        saved['attachments'][0]['quantity'] = 99
        self.w.load_draft_item(saved)
        self.assertEqual(self.w._v2_confirmation_inputs, item['attachment_confirmation_inputs'])

    def test_recover_legacy_display_id_only_from_valid_snapshot(self):
        payload = self.payload()
        del payload['items'][0]['attachments'][0]['attachment_price_id']
        restored = confirmation_payload(payload, validate=True)
        self.assertEqual(restored['items'][0]['attachments'][0]['attachment_price_id'], 101)
        self.assertNotIn('attachment_price_id', payload['items'][0]['attachments'][0])

    def test_invalid_or_changed_selection_fails_before_network_with_named_row(self):
        cases = []
        missing = self.payload()
        missing['items'][0]['attachment_confirmation_inputs'][0]['attachment_price_id'] = None
        cases.append((missing, '固定底座 柜体1'))
        lost_custom = self.payload()
        del lost_custom['items'][0]['attachments'][-1]['custom']
        cases.append((lost_custom, '木托'))
        changed = self.payload()
        changed['items'][0]['attachments'][0]['attachment_price_id'] = 999
        cases.append((changed, '固定底座 柜体1'))
        no_snapshot = self.payload()
        del no_snapshot['items'][0]['attachment_confirmation_inputs']
        no_snapshot['items'][0]['attachments'][0]['attachment_price_id'] = None
        cases.append((no_snapshot, '固定底座 柜体1'))
        removed = self.payload()
        removed['items'][0]['attachments'] = []
        cases.append((removed, '附件1'))
        for payload, label in cases:
            with self.subTest(label=label), patch('urllib.request.urlopen') as transport:
                with self.assertRaisesRegex(ValueError, label):
                    self.w.export_workbook(str(ROOT / 'outputs/should-not-be-written.xlsx'), payload)
                transport.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
