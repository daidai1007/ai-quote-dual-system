import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
if (!workbookPath) {
  throw new Error("usage: verify_formula_cost_detail.mjs workbook.xlsx");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sheet = workbook.worksheets.getItemAt(2);

const normalize = (value) => String(value ?? "").replace(/\s+/g, "").trim();
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const assertClose = (actual, expected, label) => {
  assert(Number.isFinite(Number(actual)), `${label}: expected a number, got ${actual}`);
  assert(Math.abs(Number(actual) - expected) < 0.01, `${label}: expected ${expected}, got ${actual}`);
};

assert(normalize(sheet.name) === "成本明细", `unexpected sheet name: ${sheet.name}`);
const headers = sheet.getRange("A5:O5").values[0].map(normalize);
const expectedHeaders = [
  "柜号", "名称", "规格型号", "成本类别", "明细项目", "规格/说明", "计算公式/计价依据",
  "用量", "单位", "单价（元）", "单台金额（元）", "柜体数量", "行金额（元）", "数据来源", "备注",
].map(normalize);
assert(JSON.stringify(headers) === JSON.stringify(expectedHeaders), `headers changed: ${JSON.stringify(headers)}`);

const rows = sheet.getRange("A6:O40").values;
const findRow = (category, detail) => rows.find((row) => normalize(row[3]) === normalize(category)
  && normalize(row[4]) === normalize(detail));

const material = findRow("材料成本", "SECC板材");
assert(material, "material detail row missing");
assert(String(material[6]).includes("50.000000 kg × 4.0000 元/kg = 200.00 元"), `material formula missing: ${material[6]}`);
assertClose(material[7], 50, "material weight");
assertClose(material[9], 4, "material unit price");
assertClose(material[10], 200, "material unit amount");
assertClose(material[12], 400, "material line amount");

const installRail = findRow("辅材成本", "安装条");
const guideRail = findRow("辅材成本", "导轨");
assert(installRail && guideRail, "BOM detail rows missing");
assertClose(installRail[10], 40, "installation rail unit amount");
assertClose(guideRail[10], 60, "guide rail unit amount");
assert(String(installRail[13]).includes("辅材BOM清单.xlsx"), "BOM source missing");

const a4 = findRow("附件成本", "A4资料盒");
const earth = findRow("附件成本", "接地线");
assert(a4 && earth, "attachment detail rows missing");
assertClose(a4[10], 30, "A4 attachment amount");
assertClose(earth[10], 20, "earth wire attachment amount");

const spray = findRow("喷塑费用", "平光");
assert(spray, "spray formula row missing");
assert(String(spray[6]).includes("5.000000 m² × 30.0000 元/m² = 150.00 元"), `spray formula missing: ${spray[6]}`);
assertClose(spray[7], 5, "spray area");
assertClose(spray[9], 30, "spray unit price");
assertClose(spray[10], 150, "spray amount");

const management = findRow("管理费用", "管理费用");
assert(management, "management detail row missing");
assert(String(management[6]).includes("300.00 × 0.13 = 39.00 元"), `management formula missing: ${management[6]}`);

const subtotal = findRow("柜型小计", "公式法成本");
assert(subtotal, "cabinet subtotal row missing");
assertClose(subtotal[10], 755.1, "discounted unit cost");
assertClose(subtotal[12], 1510.2, "discounted line cost");

const experienceAuxiliary = rows.find((row) => normalize(row[3]) === normalize("辅材成本")
  && normalize(row[4]) === normalize("辅材成本（经验值）") && Number(row[0]) === 2);
assert(experienceAuxiliary, "experience auxiliary row missing");

const orderTotalRow = rows.find((row) => normalize(row[0]) === "合计");
assert(orderTotalRow, "order total row missing");
assertClose(orderTotalRow[12], 2625.7, "order total");

const errors = workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula cost detail regression formula errors",
});
assert((errors.matchingCells || []).length === 0, "workbook contains formula errors");

console.log("formula cost detail regression passed");
