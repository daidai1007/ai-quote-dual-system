import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
if (!workbookPath) {
  throw new Error("usage: verify_formula_cost_columns.mjs workbook.xlsx");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const formulaSheet = workbook.worksheets.getItemAt(0);
const quickSheet = workbook.worksheets.getItemAt(1);

const normalize = (value) => String(value ?? "").replace(/\s+/g, "").trim();
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const assertClose = (actual, expected, label) => {
  assert(Number.isFinite(Number(actual)), `${label}: expected a number, got ${actual}`);
  assert(Math.abs(Number(actual) - expected) < 0.01, `${label}: expected ${expected}, got ${actual}`);
};

const formulaHeaders = formulaSheet.getRange("L10:AC10").values[0].map(normalize);
const expectedFormulaHeaders = [
  "材料成本", "辅材成本", "人工成本", "喷塑费用", "管理费用",
  "底座", "侧板", "三排", "填充安装板", "灯开关/门限位", "文件夹",
  "风机滤网", "门限位器", "接地线", "前双开门", "安装板单发", "运费", "折扣",
];
assert(
  JSON.stringify(formulaHeaders) === JSON.stringify(expectedFormulaHeaders.map(normalize)),
  `formula headers changed: ${JSON.stringify(formulaHeaders)}`,
);

const quickHeaders = quickSheet.getRange("L10:Y10").values[0].map(normalize);
const expectedQuickHeaders = [
  "柜体", "底座", "侧板", "三排", "填充安装板", "灯开关/门限位", "文件夹",
  "风机滤网", "门限位器", "接地线", "前双开门", "安装板单发", "运费", "折扣",
];
assert(
  JSON.stringify(quickHeaders) === JSON.stringify(expectedQuickHeaders.map(normalize)),
  `quick headers were modified: ${JSON.stringify(quickHeaders)}`,
);

const formulaRow1 = formulaSheet.getRange("L11:AC11").values[0];
const formulaRow2 = formulaSheet.getRange("L12:AC12").values[0];
for (const [index, expected] of [700, 300, 500, 165.81, 65].entries()) {
  assertClose(formulaRow1[index], expected, `formula row 1 component ${index + 1}`);
}
for (const [index, expected] of [1800, 270, 720, 277.92, 93.6].entries()) {
  assertClose(formulaRow2[index], expected, `formula row 2 discounted component ${index + 1}`);
}
assertClose(formulaRow1[11], 80, "formula row 1 fan price");
assertClose(formulaRow1[13], 12, "formula row 1 grounding-wire price");
assertClose(formulaRow1[17], 1, "formula row 1 discount");
assertClose(formulaRow2[10], 16.2, "formula row 2 discounted folder price");
assertClose(formulaRow2[17], 0.9, "formula row 2 discount");

assertClose(formulaSheet.getRange("F11").values[0][0], 1822.81, "formula row 1 unit price");
assertClose(formulaSheet.getRange("F12").values[0][0], 3177.72, "formula row 2 unit price");

const quickRow1 = quickSheet.getRange("L11:Y11").values[0];
assertClose(quickRow1[0], 3813.5755, "quick row 1 cabinet price");
assertClose(quickRow1[7], 76, "quick row 1 fan price");
assertClose(quickRow1[9], 11.4, "quick row 1 grounding-wire price");
assertClose(quickRow1[13], 0.95, "quick row 1 discount");

const errors = workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula cost column regression formula errors",
});
assert((errors.matchingCells || []).length === 0, "workbook contains formula errors");

console.log("formula cost column regression passed");
