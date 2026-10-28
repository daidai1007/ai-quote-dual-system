"""Real recovered export transport + actual Node workbook, synthetic data only."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
import freight_export
import v3_launcher

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
CORE = Path(os.environ.get('AI_QUOTE_V3_CORE_ROOT', ROOT.parent / 'AIQuoteDualSystem/_internal/v3_core'))
os.environ['AI_QUOTE_V3_CORE_ROOT'] = str(CORE)
namespace = v3_launcher.load_v3_namespace()


def cells(file, ordinal):
    with ZipFile(file) as book:
        strings = [''.join(n.itertext()) for n in ET.fromstring(book.read('xl/sharedStrings.xml'))]
        root = ET.fromstring(book.read(f'xl/worksheets/sheet{ordinal}.xml'))
        result = {}
        for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
            value = cell.findtext('m:v', default='', namespaces=NS)
            if cell.get('t') == 's': value = strings[int(value)]
            result[cell.get('r')] = value
        return result


class VerticalExportTransport(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='export-transport-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.payload = json.loads((ROOT / 'tests/fixtures/export_formula_cost_detail.json').read_text(encoding='utf-8'))
        # Nonzero freight makes the old horizontal-address overwrite observable.
        self.payload['items'][0]['freight_fee'] = 7
        self.payload['items'][1]['freight_fee'] = 3

    def generate(self, payload, stem):
        source = self.root / (stem + '.json')
        source.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        target = self.root / (stem + '.xlsx')
        result = subprocess.run(['node', str(ROOT / 'export_dual_quote_workbook.mjs'), str(source), str(target)],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        return target

    def test_old_client_requests_keep_horizontal_layout_and_old_repair(self):
        file = self.generate(self.payload, 'old')
        self.assertEqual(cells(file, 1)['L10'], '材料成本')
        self.assertNotEqual(cells(file, 2)['J10'], '项目')
        freight_export.fill_freight_cells(file, {'公式法报价单': [14, 3], '快速报价单': [14, 3]})
        for ordinal in [1, 2]:
            table = cells(file, ordinal)
            header = next(address for address, value in table.items() if value == '运费')
            column = ''.join(c for c in header if c.isalpha())
            self.assertEqual(float(table[column+'11']), 14)
            self.assertEqual(float(table[column+'12']), 3)

    def test_vertical_freight_repair_preserves_every_zip_entry_and_formula(self):
        request = {**self.payload, 'quotation_detail_layout': 'right_vertical_v1'}
        file = self.generate(request, 'vertical')
        before = file.read_bytes()
        freight_export.fill_freight_cells(file, {'公式法报价单': [14, 3], '快速报价单': [14, 3]})
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(cells(file, 1)['L10'], '项目')
        self.assertEqual(cells(file, 2)['J10'], '项目')
        for ordinal, column, values in [(1,'L',[14,3]),(2,'J',[14,3])]:
            table = cells(file, ordinal)
            freight_rows = [a[len(column):] for a,v in table.items() if a.startswith(column) and v=='运费']
            self.assertEqual(len(freight_rows), 2)
            value_column = 'M' if ordinal==1 else 'K'
            self.assertEqual([float(table[value_column+r]) for r in freight_rows], values)

    def test_actual_recovered_http_export_opts_in_without_mutating_snapshot(self):
        original = deepcopy(self.payload)
        received = []
        def response(request, *args, **kwargs):
            self.assertEqual(request.full_url, 'http://127.0.0.1:9/api/quotes/export')
            body = json.loads(request.data)
            received.append(body)
            return io.BytesIO(self.generate(body, 'response').read_bytes())
        file = self.root/'downloaded.xlsx'
        with patch('urllib.request.urlopen', side_effect=response):
            namespace['MainWindow'].export_workbook(SimpleNamespace(base_url=lambda:'http://127.0.0.1:9'), file, self.payload)
        self.assertEqual(self.payload, original)
        self.assertEqual(received[0]['quotation_detail_layout'], 'right_vertical_v1')
        self.assertEqual(cells(file, 1)['L10'], '项目')
        self.assertEqual(cells(file, 2)['J10'], '项目')
        self.assertEqual(file.read_bytes(), (self.root/'response.xlsx').read_bytes())

    def test_new_client_can_download_legacy_server_output(self):
        received=[]
        def legacy_response(request, *args, **kwargs):
            body=json.loads(request.data);received.append(deepcopy(body))
            body.pop('quotation_detail_layout')
            return io.BytesIO(self.generate(body,'legacy-response').read_bytes())
        file=self.root/'legacy-downloaded.xlsx'
        with patch('urllib.request.urlopen',side_effect=legacy_response):
            namespace['MainWindow'].export_workbook(SimpleNamespace(base_url=lambda:'http://127.0.0.1:9'),file,self.payload)
        self.assertEqual(received[0]['quotation_detail_layout'],'right_vertical_v1')
        self.assertEqual(cells(file,1)['L10'],'材料成本')


if __name__ == '__main__':
    unittest.main()
