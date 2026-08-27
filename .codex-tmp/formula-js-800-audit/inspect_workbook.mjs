import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "G:/gongsi/banjinxitong/板件后续二次修改/数据库备份/公式法报价/材料重量/JS,JP,JA,JE,JK,JM计算表.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));

const js = workbook.worksheets.getItem("JS");
js.getRange("B6:B8").values = [[800], [800], [800]];
js.getRange("B11").values = [[0]];
js.getRange("B17").values = [[1]];
const inputs = js.getRange("A5:B17");
console.log(JSON.stringify({
  inputs: inputs.values.map((row, index) => ({ row: index + 5, label: row[0], value: row[1] })),
}, null, 2));

const detailRange = js.getRange("E5:Y28");
const values = detailRange.values;
const formulas = detailRange.formulas;
const selectedColumns = [0, 3, 8, 9, 20]; // E, H, M, N, Y
const details = values.map((row, index) => ({
  row: index + 5,
  values: selectedColumns.map((column) => row[column]),
  formulas: selectedColumns.map((column) => formulas[index][column]),
})).filter((row) => row.values.some((value) => value !== null && value !== "" && value !== 0));
console.log(JSON.stringify({ details }, null, 2));

for (const address of ["E26:N28", "H28", "N28"]) {
  const range = js.getRange(address);
  console.log(JSON.stringify({ address, values: range.values, formulas: range.formulas }, null, 2));
}
