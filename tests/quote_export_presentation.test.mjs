import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";
import ExcelJS from "@excel.js/exceljs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const fixturePath = path.join(projectRoot, "tests", "fixtures", "export_formula_cost_detail.json");
const doorMatrixFixturePath = path.join(projectRoot, "tests", "fixtures", "export_quick_door_matrix.json");
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

test("door limiter and reinforcement quantities reach quick columns and cost-detail BOM", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-door-limiter-"));
  const inputPath = path.join(tempDir, "door-limiter-input.json");
  const outputPath = path.join(tempDir, "door-limiter-output.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    payload.items = [payload.items[0]];
    const item = payload.items[0];
    item.attachments = [
      {
        item_name: "门限位器",
        quantity: 4,
        unit_price: 25,
        price_source: "测试附件价格",
      },
      {
        item_name: "门加强筋",
        quantity: 4,
        unit_price: 30,
        price_source: "测试附件价格",
      },
    ];
    item.formula.attachment_fee = 220;
    item.formula.total_cost = 1009;
    item.quick.attachment_fee = 220;
    item.quick.total_cost = 3370;
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    const formulaSheet = workbook.getWorksheet("公式法报价单");
    const quickSheet = workbook.getWorksheet("快速报价单");
    closeTo(formulaSheet.getCell("X11").value, 90, "formula limiter amount after discount");
    const limiterColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门限位器");
    assert.ok(limiterColumn > 0, "quick limiter name column is missing");
    closeTo(quickSheet.getCell(11, limiterColumn).value, 100, "quick limiter amount");
    const reinforcementColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门加强筋");
    assert.ok(reinforcementColumn > 0, "quick reinforcement name column is missing");
    closeTo(quickSheet.getCell(11, reinforcementColumn).value, 120, "quick reinforcement amount");
    assert.deepEqual(
      ["L11", "M11", "N11", "O11", "P11"].map((cell) => Number(formulaSheet.getCell(cell).value)),
      [180, 90, 270, 135, 35.1],
      "other formula components changed",
    );
    closeTo(quickSheet.getCell("L11").value, 3150, "quick cabinet amount excluding attachments");

    const detailSheet = workbook.getWorksheet("成本明细");
    let limiterRow = null;
    let reinforcementRow = null;
    detailSheet.eachRow((row) => {
      if (row.getCell(5).text === "门限位器") limiterRow = row;
      if (row.getCell(5).text === "门加强筋") reinforcementRow = row;
    });
    assert.ok(limiterRow, "door limiter BOM row is missing");
    closeTo(limiterRow.getCell(8).value, 4, "door limiter BOM quantity");
    closeTo(limiterRow.getCell(10).value, 25, "door limiter BOM unit price");
    closeTo(limiterRow.getCell(11).value, 100, "door limiter BOM amount");
    assert.ok(reinforcementRow, "door reinforcement BOM row is missing");
    closeTo(reinforcementRow.getCell(8).value, 4, "door reinforcement BOM quantity");
    closeTo(reinforcementRow.getCell(10).value, 30, "door reinforcement BOM unit price");
    closeTo(reinforcementRow.getCell(11).value, 120, "door reinforcement BOM amount");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

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

    const quickFormulaCell = workbook.getWorksheet("快速报价单").getCell("K11");
    assert.equal(
      quickFormulaCell.value.formula,
      "L11*R11+M11+N11",
    );
    closeTo(quickFormulaCell.value.result, 3200, "quick Excel formula cached result");

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

test("quick workbook uses stable selected-name columns and non-discounted door surcharges", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-door-matrix-export-"));
  const outputPath = path.join(tempDir, "door-matrix.xlsx");
  const reversedInputPath = path.join(tempDir, "door-matrix-reversed.json");
  const reversedOutputPath = path.join(tempDir, "door-matrix-reversed.xlsx");
  try {
    await runExporter(outputPath, doorMatrixFixturePath);
    const reversed = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
    reversed.items.reverse();
    await fs.writeFile(reversedInputPath, JSON.stringify(reversed), "utf8");
    await runExporter(reversedOutputPath, reversedInputPath);

    const workbook = new ExcelJS.Workbook();
    const reversedWorkbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    await reversedWorkbook.xlsx.readFile(reversedOutputPath);
    const sheet = workbook.getWorksheet("快速报价单");
    const reversedSheet = reversedWorkbook.getWorksheet("快速报价单");
    const headers = sheet.getRow(10).values.slice(11).filter((value) => value !== null && value !== undefined && value !== "");
    const reversedHeaders = reversedSheet.getRow(10).values.slice(11).filter((value) => value !== null && value !== undefined && value !== "");
    assert.deepEqual(headers, reversedHeaders, "dynamic attachment order changed with quote row order");
    assert.deepEqual(headers.slice(0, 2), ["成本计算公式", "柜体"]);
    assert.deepEqual(headers.slice(-4), ["其他附件/差额", "配置变形说明", "配置变形", "折扣"]);
    const dynamicNames = headers.slice(2, -4);
    assert.deepEqual(new Set(dynamicNames), new Set([
      "固定底座100高", "红绿接地线", "JA内门板", "JP通风顶罩", "KA2206风机", "门限位器",
    ]));
    assert.ok(!dynamicNames.includes("侧板"), "unselected attachment produced a blank column");

    const headerIndex = (label) => sheet.getRow(10).values.findIndex((value) => value === label);
    const descriptionColumn = headerIndex("配置变形说明");
    const surchargeColumn = headerIndex("配置变形");
    const discountColumn = headerIndex("折扣");
    assert.equal(surchargeColumn, descriptionColumn + 1, "configuration text is not immediately before its numeric cell");
    const expected = [
      ["", "", 990],
      ["后背板变单开门+150", 150, 1070],
      ["单开门变为双开门+60", 60, 1140],
      ["单开门/后背板均变为双开门+420", 420, 1640],
      ["单门和双门+270", 270, 1200],
    ];
    expected.forEach(([description, surcharge, total], index) => {
      const row = 11 + index;
      assert.equal(sheet.getCell(row, descriptionColumn).text, description);
      assert.equal(sheet.getCell(row, surchargeColumn).value ?? "", surcharge);
      closeTo(sheet.getCell(row, 6).value, total, `door matrix quick total row ${row}`);
      const formula = sheet.getCell(row, 11).value.formula;
      assert.match(formula, new RegExp(`${sheet.getColumn(discountColumn).letter}${row}`));
      if (surcharge) assert.match(formula, new RegExp(`${sheet.getColumn(surchargeColumn).letter}${row}`));
    });

    for (let row = 11; row <= 15; row += 1) {
      for (const name of dynamicNames) {
        const column = headerIndex(name);
        const selectedName = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8")).items[row - 11]
          .attachments.map((item) => item.item_name);
        if (!selectedName.includes(name)) assert.equal(sheet.getCell(row, column).value, null);
      }
    }
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
