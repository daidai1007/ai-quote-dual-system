import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const source = path.resolve('.codex-tmp/cost-detail-export-1');
try {
const expected = JSON.parse(await fs.readFile(path.join(source, 'expected.json'), 'utf8'));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(source, '成本明细.xlsx')));
const sheet = workbook.worksheets.getItem('成本明细');
const actual = sheet.getRange(`A1:K${expected.rows.length + 3}`).values;
if (actual[0][0] !== expected.title || actual[1][0] !== expected.meta) throw new Error('Title/meta mismatch');
for (let column = 0; column < 11; column++) {
  if (actual[2][column] !== expected.headers[column]) throw new Error(`Header mismatch: ${column}`);
}
let verified = 0;
for (let row = 0; row < expected.rows.length; row++) {
  for (let column = 0; column < 11; column++) {
    const text = expected.rows[row][column];
    const value = actual[row + 3][column];
    const numeric = expected.numeric_columns.includes(column);
    if (numeric ? (typeof value !== 'number' || value !== Number(text.replaceAll(',', '')))
                : (value ?? '') !== text) throw new Error(`Cell mismatch: ${row},${column}`);
    verified++;
  }
}
const preview = await workbook.render({sheetName: '成本明细', range: 'A1:K12', scale: 1, format: 'png'});
await fs.writeFile(path.join(source, 'excel-preview.png'), new Uint8Array(await preview.arrayBuffer()));
console.log(JSON.stringify({independent_import: true, checked_cells: verified, headers: 11, rows: expected.rows.length, preview: 'excel-preview.png'}));
} catch (error) {
  console.error(String(error.message));
  process.exitCode = 1;
}
