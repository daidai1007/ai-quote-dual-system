"""Read only: preserve raw cells, formulas and SHA-256. Never save the workbook."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import openpyxl

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
source_bytes = args.source.read_bytes()
book = openpyxl.load_workbook(io.BytesIO(source_bytes), data_only=False)
result = {'source_file': args.source.name, 'sha256': hashlib.sha256(source_bytes).hexdigest(), 'sheets': {}}
for sheet_name in ('快速报价', '公式法报价'):
    sheet = book[sheet_name]
    headers = [cell.value for cell in sheet[1]]
    rows = []
    for row in sheet.iter_rows(min_row=2):
        if all(cell.value is None for cell in row):
            continue
        rows.append({'source_row_no': row[0].row, 'values': {str(h): c.value for h, c in zip(headers, row) if h},
                     'cells': {c.coordinate: {'value': c.value, 'type': c.data_type} for c in row if c.value is not None}})
    result['sheets'][sheet_name] = rows
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'sha256': result['sha256'], 'rows': {k: len(v) for k, v in result['sheets'].items()}}, ensure_ascii=False))
