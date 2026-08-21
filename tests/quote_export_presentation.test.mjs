import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";
import ExcelJS from "@excel.js/exceljs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const fixturePath = path.join(projectRoot, "tests", "fixtures", "export_formula_cost_detail.json");
const exporterPath = path.join(projectRoot, "export_dual_quote_workbook.mjs");

const runExporter = (outputPath) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [exporterPath, fixturePath, outputPath], {
    cwd: projectRoot,
    windowsHide: true,
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (data) => { stdout += data.toString(); });
  child.stderr.on("data", (data) => { stderr += data.toString(); });
  child.on("error", reject);
  child.on("close", (code) => {
    if (code === 0) resolve();
    else reject(new Error(stderr.trim() || stdout.trim() || `exporter exited with code ${code}`));
  });
});

const closeTo = (actual, expected, label) => {
  assert.ok(Number.isFinite(Number(actual)), `${label} is not numeric: ${actual}`);
  assert.ok(Math.abs(Number(actual) - expected) < 0.01, `${label}: expected ${expected}, got ${actual}`);
};

const xlsxEntryNames = (buffer) => {
  const names = [];
  for (let offset = 0; offset + 46 <= buffer.length;) {
    if (buffer.readUInt32LE(offset) !== 0x02014b50) {
      offset += 1;
      continue;
    }
    const nameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    const commentLength = buffer.readUInt16LE(offset + 32);
    const nameStart = offset + 46;
    names.push(buffer.toString("utf8", nameStart, nameStart + nameLength));
    offset = nameStart + nameLength + extraLength + commentLength;
  }
  return names;
};

test("formal workbook exports the revised presentation without changing quote detail", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-export-presentation-"));
  const outputPath = path.join(tempDir, "presentation-regression.xlsx");
  try {
    await runExporter(outputPath);
    const stat = await fs.stat(outputPath);
    assert.ok(stat.size > 0, "exported workbook is empty");
    const annotationPattern = /^(?:xl\/comments\d+\.xml|xl\/threadedComments\/|xl\/persons\/|xl\/drawings\/vmlDrawing\d+\.vml)/i;
    const entryNames = xlsxEntryNames(await fs.readFile(outputPath));
    assert.ok(entryNames.includes("xl/workbook.xml"), "XLSX ZIP directory could not be parsed");
    const annotationEntries = entryNames.filter((name) => annotationPattern.test(name));
    assert.deepEqual(annotationEntries, [], "workbook contains legacy or threaded annotation objects");

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    assert.deepEqual(workbook.worksheets.map((sheet) => sheet.name), [
      "公式法报价单", "快速报价单", "成本明细",
    ]);

    const expectedSeller = [
      "浙江京能电力设备有限公司",
      "杭州临安横畈工业功能区桑园路18号",
      "0571-88520091",
      "0571-88520077",
      "",
    ];
    for (const [sheetName, expectedAmounts] of [
      ["公式法报价单", [[755.1, 1510.2], [1115.5, 1115.5]]],
      ["快速报价单", [[3200, 6400], [4100, 4100]]],
    ]) {
      const sheet = workbook.getWorksheet(sheetName);
      assert.equal(sheet.getCell("G10").text, "总价");
      assert.deepEqual([4, 5, 6, 7, 8].map((row) => sheet.getCell(row, 6).text), expectedSeller);
      expectedAmounts.forEach(([unitPrice, totalPrice], index) => {
        closeTo(sheet.getCell(11 + index, 6).value, unitPrice, `${sheetName} unit price row ${11 + index}`);
        closeTo(sheet.getCell(11 + index, 7).value, totalPrice, `${sheetName} total price row ${11 + index}`);
      });
    }

    const detailSheet = workbook.getWorksheet("成本明细");
    assert.ok(detailSheet.model.merges.includes("A3:O3"), "cost-detail explanation merge was lost");
    assert.match(detailSheet.getCell("A3").text, /^说明：/, "cost-detail explanation was lost");
    const detailRows = [];
    detailSheet.eachRow({ includeEmpty: false }, (row) => detailRows.push(row.values.slice(1).map(String)));
    assert.ok(detailRows.some((row) => row.includes("安装条")), "BOM row was lost");
    assert.ok(detailRows.some((row) => row.includes("A4资料盒")), "attachment row was lost");
    assert.ok(detailRows.some((row) => row.includes("接地线")), "second attachment row was lost");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
