"""Freight presentation through real Qt controls and the real export entry point.

The transport is stubbed; no quote confirmation or database write is performed.
No interface screenshots are captured.
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import verify_drawing_workflow as base
from freight_state import money

ROOT = Path(__file__).resolve().parents[1]
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


class FreightOutputTests(unittest.TestCase):
    setUp = base.DrawingWorkflowTests.setUp
    tearDown = base.DrawingWorkflowTests.tearDown
    accept = base.DrawingWorkflowTests.accept

    def amounts(self, amount):
        self.assertEqual(self.w.freight_spin.text().strip(), f'{amount:.2f} 元')
        for labels in (self.w.formula_labels, self.w.quick_labels):
            self.assertEqual(labels['freight'].text(), f'{amount:.2f} 元')

    def item(self, freight=66.1, quantity=1):
        result = base.response()
        return dict(name='运费回归柜', model_code='600*300*1800',
                    specification='600*300*1800', product_code='JS_SINGLE',
                    product_family='JS', width_mm=600, depth_mm=300, height_mm=1800,
                    material_code='SECC', coating_type='平光', single_door_count=1,
                    double_door_count=0, quantity=quantity, freight_fee=freight,
                    formula=result['formula_cost'], quick=result['quick_quote'],
                    formula_discount=1, quick_discount=1, attachments=[], notes='保留原备注')

    def test_auto_manual_recalculate_reset_and_totals(self):
        self.amounts(0)
        self.accept(base.response(66.1))
        self.amounts(66.1)
        self.assertEqual(self.w.freight_state.mode, 'AUTO')
        self.assertEqual(self.w.formula_labels['total'].text(), '228.70 元')
        self.assertEqual(self.w.quick_labels['total'].text(), '266.10 元')
        self.w.freight_spin.setFocus()
        self.w.freight_spin.selectAll()
        base.QTest.keyClicks(self.w.freight_spin, '50')
        base.QTest.keyClick(self.w.freight_spin, base.Qt.Key.Key_Return)
        self.amounts(50)
        self.assertEqual(self.w.freight_state.mode, 'MANUAL')
        self.w.width_spin.setValue(750)
        self.accept(base.response(99.9))
        self.amounts(50)
        for _ in range(3):
            self.w.refresh_discounted_totals()
        self.assertEqual(self.w.formula_labels['total'].text(), '212.60 元')
        self.assertEqual(self.w.quick_labels['total'].text(), '250.00 元')
        self.assertEqual(self.w.current_result['formula']['total_cost'], 162.6)
        self.assertEqual(self.w.current_result['quick']['total_cost'], 200)
        self.w.formula_discount.setValue(0.9)
        self.w.quick_discount.setValue(0.8)
        self.amounts(50)
        self.assertEqual(self.w.formula_labels['total'].text(), '196.34 元')
        self.assertEqual(self.w.quick_labels['total'].text(), '210.00 元')
        self.w.reset_current_cabinet()
        self.amounts(0)
        self.assertEqual(self.w.freight_state.mode, 'AUTO')
        self.accept(base.response(72.33))
        self.amounts(72.33)
        self.accept(base.response(None))
        self.amounts(0)

    def test_freight_remains_visible_on_attachment_error(self):
        self.accept(base.response())
        self.w.freight_spin.setValue(50)
        self.w.attachments = [{'status': 'ERROR', 'quantity': 1}]
        self.w.refresh_discounted_totals()
        self.amounts(50)
        self.assertEqual(self.w.formula_labels['attachment'].text(), '附件成本错误')

    def test_summary_saved_amount_no_layout_or_total_change(self):
        items = [self.item(66.1, 2), self.item(50), self.item(0)]
        before = copy.deepcopy(items)
        table = self.w.summary_table
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.w.draft_items = items
        self.w.refresh_summary()
        heights = [table.rowHeight(r) for r in range(table.rowCount())]
        self.w.freight_spin.setValue(123)  # unrelated current cabinet
        self.w.refresh_summary()
        self.assertEqual(headers, [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())])
        self.assertEqual(heights, [table.rowHeight(r) for r in range(table.rowCount())])
        column = next(c for c, h in enumerate(headers) if '备注' in h)
        for row, amount in enumerate((66.1, 50, 0)):
            self.assertTrue(table.item(row, column).text().startswith(f'运费：{amount:.2f} 元；'))
            self.assertEqual(table.item(row, column).text().count('运费：'), 1)
        self.assertIn('132.20 元', table.item(0, column).toolTip())
        self.assertEqual(items, before)
        self.assertEqual(self.w.summary_formula_total.text(), '公式法：832.60 元')
        self.assertEqual(self.w.summary_quick_total.text(), '快速报价：982.20 元')

    def test_saved_draft_restore_keeps_freight(self):
        self.w.load_draft_item(self.item(50))
        self.amounts(50)

    def test_add_to_summary_captures_auto_and_manual_before_reset(self):
        for amount, mode in ((66.1, 'AUTO'), (50, 'MANUAL')):
            self.w.width_spin.setValue(600)
            self.w.depth_spin.setValue(300)
            self.w.height_spin.setValue(1800)
            self.w.quote_spec_edit.setText('600*300*1800')
            self.w.quantity_spin.setValue(2)
            if mode == 'MANUAL':
                self.w.freight_spin.setValue(amount)
            self.accept(base.response(66.1))
            count = len(self.w.draft_items)
            self.w.add_current_to_summary()
            self.assertEqual(len(self.w.draft_items), count + 1)
            item = self.w.draft_items[-1]
            self.assertEqual(item['freight_fee'], amount)
            self.amounts(0)
            self.assertEqual(self.w.freight_state.mode, 'AUTO')
            self.w.load_draft_item(item)
            self.amounts(amount)
            self.assertEqual(self.w.freight_state.mode, mode)
            self.w.reset_current_cabinet()

    def test_legacy_draft_manual_mode_survives_recalculation(self):
        self.w.load_draft_item(self.item(50))
        self.assertEqual(self.w.freight_state.mode, 'MANUAL')
        self.accept(base.response(66.1))
        self.amounts(50)

    def test_invalid_money_is_zero(self):
        for value in (None, '', 'invalid', float('nan'), float('inf'), -1):
            self.assertEqual(str(money(value)), '0.00')

    def test_export_real_endpoint_adapter_preserves_totals_and_layout(self):
        payload = json.loads((ROOT / 'tests/fixtures/export_formula_cost_detail.json').read_text('utf-8'))
        sample = payload['items'][0]
        payload['items'] = []
        for freight, quantity in ((66.1, 1), (50, 2), (0, 1)):
            item = copy.deepcopy(sample)
            item.update(freight_fee=freight, quantity=quantity)
            payload['items'].append(item)
        unchanged = copy.deepcopy(payload)
        with tempfile.TemporaryDirectory(dir=ROOT / 'outputs', prefix='freight-output-') as directory:
            directory = Path(directory)
            input_path, server_path, output_path = [directory / n for n in ('input.json', 'server.xlsx', 'client.xlsx')]
            input_path.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')
            completed = subprocess.run(['node', 'export_dual_quote_workbook.mjs', str(input_path), str(server_path)],
                                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with ZipFile(server_path) as archive:
                original = {name: archive.read(name) for name in archive.namelist()}
            # Simulate the reported blank amount while retaining the server's
            # accepted totals/formulas. Also test an omitted cell and zero.
            damaged = dict(original)
            freight_columns = {}
            shared = [''.join(n.itertext()) for n in ET.fromstring(original['xl/sharedStrings.xml'])]
            for name in ('xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml'):
                xml = damaged[name].decode('utf-8')
                header = next(c for c in ET.fromstring(xml).findall('.//m:c', NS)
                              if c.get('t') == 's' and shared[int(c.find('m:v', NS).text)] == '运费')
                column = re.match('[A-Z]+', header.get('r'))[0]
                freight_columns[name] = column
                for row in (11, 12):
                    xml = re.sub(rf'<c\b[^>]*r="{column}{row}"[^>]*>.*?</c>',
                                 f'<c r="{column}{row}" s="12"/>' if row == 11 else '', xml)
                damaged[name] = xml.encode('utf-8')
            from io import BytesIO
            buffer = BytesIO()
            with ZipFile(buffer, 'w') as archive:
                for name, data in damaged.items():
                    archive.writestr(name, data)
            response = base.Mock()
            response.__enter__ = lambda _: response
            response.__exit__ = lambda *args: None
            response.read.return_value = buffer.getvalue()
            with patch('urllib.request.urlopen', return_value=response) as transport:
                self.w.export_workbook(str(output_path), payload)
            request = transport.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/api/quotes/export'))
            self.assertEqual(json.loads(request.data), unchanged)
            self.assertEqual(payload, unchanged)
            with ZipFile(output_path) as archive:
                repaired = {name: archive.read(name) for name in archive.namelist()}
            self.assertEqual(original.keys(), repaired.keys())
            styles = ET.fromstring(repaired['xl/styles.xml']).find('m:cellXfs', NS)
            for name in original:
                if name not in freight_columns and name != 'xl/styles.xml':
                    self.assertEqual(repaired[name], original[name], name)
            for name, column in freight_columns.items():
                before = {c.get('r'): c for c in ET.fromstring(original[name]).findall('.//m:c', NS)}
                after = {c.get('r'): c for c in ET.fromstring(repaired[name]).findall('.//m:c', NS)}
                for row, expected in ((11, '66.10'), (12, '100.00'), (13, '0.00')):
                    cell = after[f'{column}{row}']
                    self.assertEqual(cell.find('m:v', NS).text, expected)
                    self.assertEqual(styles[int(cell.get('s'))].get('numFmtId'), '2')
                for reference in before:
                    if reference not in [f'{column}{row}' for row in (11, 12, 13)]:
                        self.assertEqual(ET.tostring(before[reference]), ET.tostring(after[reference]), reference)
                # Row height, column widths, merges, drawings and print layout.
                old_root, new_root = ET.fromstring(original[name]), ET.fromstring(repaired[name])
                old_root.remove(old_root.find('m:sheetData', NS))
                new_root.remove(new_root.find('m:sheetData', NS))
                self.assertEqual(ET.tostring(old_root), ET.tostring(new_root))


if __name__ == '__main__':
    unittest.main(verbosity=2)
