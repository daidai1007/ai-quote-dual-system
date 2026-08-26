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
  "底座", "侧板", "三排纵梁", "安装板", "灯/开关", "文件夹",
  "风机滤网", "门限位器", "接地线", "双开门", "安装板单发", "运费", "折扣",
];
assert(
  JSON.stringify(formulaHeaders) === JSON.stringify(expectedFormulaHeaders.map(normalize)),
  `formula headers changed: ${JSON.stringify(formulaHeaders)}`,
);

const quickHeaders = quickSheet.getRange("K10:AF10").values[0].map(normalize);
const expectedQuickHeaders = [
  "成本计算公式", "柜体", "底座", "侧板", "三排纵梁", "安装板", "内门", "玻璃门",
  "通风顶罩", "防雨顶", "分段板", "JK安装板", "灯/开关", "文件夹", "风机滤网",
  "门限位器", "接地线", "双开门", "安装板单发", "运费", "其他附件/差额", "折扣",
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

assertClose(formulaSheet.getRange("F11").values[0][0], 2122.81, "formula row 1 unit price");
assertClose(formulaSheet.getRange("F12").values[0][0], 3177.72, "formula row 2 unit price");

const quickRow1 = quickSheet.getRange("K11:AF11").values[0];
const expectedQuickFormula = "=(L11+M11+Q11)*AF11+Y11+AA11";
assert(
  quickSheet.getRange("K11").formulas[0][0] === expectedQuickFormula,
  `quick Excel formula changed: ${quickSheet.getRange("K11").formulas[0][0]}`,
);
assertClose(quickRow1[0], 4190.5755, "quick row 1 Excel formula result");
assertClose(quickRow1[1], 4014.29, "quick row 1 original cabinet price");
assertClose(quickRow1[2], 100, "quick row 1 original base price");
assertClose(quickRow1[6], 200, "quick row 1 original inner-door price");
assertClose(quickRow1[14], 80, "quick row 1 original fan price");
assertClose(quickRow1[16], 12, "quick row 1 original grounding-wire price");
assertClose(quickRow1[21], 0.95, "quick row 1 discount");
assertClose(quickSheet.getRange("F11").values[0][0], 4190.5755, "selectively discounted quick unit price");
assert(
  quickSheet.getRange("K12").formulas[0][0] === "=L12*AF12+X12",
  `quick row 2 should omit blank and zero cells: ${quickSheet.getRange("K12").formulas[0][0]}`,
);

const errors = workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula cost column regression formula errors",
});
assert((errors.matchingCells || []).length === 0, "workbook contains formula errors");

console.log("formula cost column regression passed");
