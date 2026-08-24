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

const runExporter = (outputPath, inputPath = fixturePath) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [exporterPath, inputPath, outputPath], {
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

test("formal workbook replaces only the door phrase using current door counts", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-door-remark-"));
  const inputPath = path.join(tempDir, "door-remark-input.json");
  const outputPath = path.join(tempDir, "door-remark-output.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const base = payload.items[0];
    const staleRemark = "手工录入，碳钢喷塑RAL7035橘纹，前双开门后背板，配风机1个。";
    const cases = [
      [1, 0, "前单开门"],
      [0, 1, "前双开门"],
      [2, 0, "前后单开门"],
      [0, 2, "前后双开门"],
      [1, 1, "前单开门后双开门"],
    ];
    payload.items = cases.map(([single, double], index) => ({
      ...structuredClone(base),
      source_pdf_name: `手工录入-${index + 1}.pdf`,
      product_code: double > 0 && single === 0 ? "JS_DOUBLE" : "JS_SINGLE",
      variant_code: double > 0 && single === 0 ? "DOUBLE" : "SINGLE",
      variant_name: `单门${single} 双门${double}`,
      single_door_count: single,
      double_door_count: double,
      final_remark: staleRemark,
      notes: staleRemark,
      source_ocr_remark: staleRemark,
    }));
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    for (const sheetName of ["公式法报价单", "快速报价单"]) {
      const sheet = workbook.getWorksheet(sheetName);
      cases.forEach(([, , expected], index) => {
        assert.equal(
          sheet.getCell(11 + index, 8).text,
          staleRemark.replace("前双开门后背板", expected),
        );
      });
    }
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
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
