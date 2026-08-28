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
    closeTo(formulaSheet.getCell("X11").value, 90, "formula limiter per-cabinet amount after discount");
    const limiterColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门限位器");
    assert.ok(limiterColumn > 0, "quick limiter name column is missing");
    closeTo(quickSheet.getCell(11, limiterColumn).value, 100, "quick limiter per-cabinet amount");
    const reinforcementColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门加强筋");
    assert.ok(reinforcementColumn > 0, "quick reinforcement name column is missing");
    closeTo(quickSheet.getCell(11, reinforcementColumn).value, 120, "quick reinforcement per-cabinet amount");
    assert.deepEqual(
      ["L11", "M11", "N11", "O11", "P11"].map((cell) => Number(formulaSheet.getCell(cell).value)),
      [180, 90, 270, 135, 35.1],
      "other formula components changed",
    );
    closeTo(quickSheet.getCell("L11").value, 3150, "quick cabinet per-cabinet amount excluding attachments");

    const detailSheet = workbook.getWorksheet("成本明细");
    let limiterRow = null;
    let reinforcementRow = null;
    detailSheet.eachRow((row) => {
      if (row.getCell(5).text === "门限位器") limiterRow = row;
      if (row.getCell(5).text === "门加强筋") reinforcementRow = row;
    });
    assert.ok(limiterRow, "door limiter BOM row is missing");
    closeTo(limiterRow.getCell(8).value, 8, "door limiter BOM final quantity");
    closeTo(limiterRow.getCell(10).value, 25, "door limiter BOM unit price");
    closeTo(limiterRow.getCell(11).value, 200, "door limiter BOM amount");
    assert.ok(reinforcementRow, "door reinforcement BOM row is missing");
    closeTo(reinforcementRow.getCell(8).value, 8, "door reinforcement BOM final quantity");
    closeTo(reinforcementRow.getCell(10).value, 30, "door reinforcement BOM unit price");
    closeTo(reinforcementRow.getCell(11).value, 240, "door reinforcement BOM amount");
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

    const quickSheet = workbook.getWorksheet("快速报价单");
    const quickFormulaCell = quickSheet.getCell("K11");
    const discountColumn = quickSheet.getRow(10).values.findIndex(
      (value) => value === "折扣",
    );
    assert.equal(
      quickFormulaCell.value.formula,
      `L11*${quickSheet.getColumn(discountColumn).letter}11+M11+N11`,
    );
    closeTo(quickFormulaCell.value.result, 3200, "quick Excel unit formula cached result");

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

test("quick workbook uses stable selected-name columns without obsolete configuration columns", async () => {
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
    const formulaSheet = workbook.getWorksheet("公式法报价单");
    const headers = sheet.getRow(10).values.slice(11).filter((value) => value !== null && value !== undefined && value !== "");
    const reversedHeaders = reversedSheet.getRow(10).values.slice(11).filter((value) => value !== null && value !== undefined && value !== "");
    assert.deepEqual(headers, reversedHeaders, "dynamic attachment order changed with quote row order");
    assert.deepEqual(headers.slice(0, 2), ["成本计算公式", "柜体"]);
    assert.deepEqual(headers.slice(-2), ["运费", "折扣"]);
    assert.ok(!headers.includes("其他附件/差额"));
    assert.ok(!headers.includes("配置变形说明"));
    assert.ok(!headers.includes("配置变形"));
    const dynamicNames = headers.slice(2, -2);
    assert.deepEqual(new Set(dynamicNames), new Set([
      "固定底座100高", "标准安装板", "JA内门板", "JP通风顶罩", "KA2206风机", "门限位器",
      "侧板",
      "JS、JP后背板改为单开门", "JS、JP单开门改为双开门",
      "JS、JP后背板改为双开门", "JA、JE单开门改为双开门",
    ]));

    const headerIndex = (label) => sheet.getRow(10).values.findIndex((value) => value === label);
    const discountColumn = headerIndex("折扣");
    const expected = [
      [990, 990], [960, 960], [1140, 1140], [1640, 4920], [1290, 2580],
      [1980, 3960],
    ];
    expected.forEach(([unitTotal, lineTotal], index) => {
      const row = 11 + index;
      closeTo(sheet.getCell(row, 6).value, unitTotal, `door matrix quick unit total row ${row}`);
      closeTo(sheet.getCell(row, 7).value, lineTotal, `door matrix quick line total row ${row}`);
      const formula = sheet.getCell(row, 11).value.formula;
      assert.match(formula, new RegExp(`${sheet.getColumn(discountColumn).letter}${row}`));
    });
    const boardColumn = headerIndex("标准安装板");
    assert.equal(sheet.getCell(12, boardColumn).value, -100);
    assert.match(sheet.getCell(12, 11).value.formula, new RegExp(`${sheet.getColumn(boardColumn).letter}12`));
    const formulaBoardColumn = formulaSheet.getRow(10).values.findIndex((value) => value === "安装板");
    assert.ok(formulaBoardColumn > 0);
    assert.equal(formulaSheet.getCell(12, formulaBoardColumn).value, -90);

    for (let row = 11; row <= 16; row += 1) {
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

test("quick workbook creates the other-attachment column only for a real unlisted delta", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-other-delta-export-"));
  const inputPath = path.join(tempDir, "other-delta.json");
  const outputPath = path.join(tempDir, "other-delta.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
    payload.items = [payload.items[0]];
    payload.items[0].quick.attachment_fee = 125;
    payload.items[0].quick.total_cost = 1125;
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    const sheet = workbook.getWorksheet("快速报价单");
    const headers = sheet.getRow(10).values;
    const otherColumn = headers.findIndex((value) => value === "其他附件/差额");
    const discountColumn = headers.findIndex((value) => value === "折扣");
    assert.ok(otherColumn > 0);
    assert.equal(headers.includes("配置变形说明"), false);
    assert.equal(headers.includes("配置变形"), false);
    assert.equal(sheet.getCell(11, otherColumn).value, 25);
    assert.equal(sheet.getCell(11, 11).value.formula, `(L11+M11)*${sheet.getColumn(discountColumn).letter}11+${sheet.getColumn(otherColumn).letter}11`);
    closeTo(sheet.getCell(11, 6).value, 1015, "quick delta row total");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("workbook uses final attachment quantities with the three manual exceptions", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-attachment-quantity-"));
  const inputPath = path.join(tempDir, "attachment-quantity.json");
  const outputPath = path.join(tempDir, "attachment-quantity.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.quantity = 3;
    item.freight_fee = 50;
    item.formula_discount = 0.9;
    item.quick_discount = 0.9;
    item.attachments = [
      { item_name: "标准安装板", category_level1: "安装板", quantity: 1, unit_price: 100, attachment_price_sign: -1 },
      { item_name: "侧板", category_level1: "侧板", quantity: 2, unit_price: 50 },
      { item_name: "KA2206风机", category_level1: "风机滤网", quantity: 1, unit_price: 30 },
      { item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1, unit_price: 150 },
      { item_name: "门安装条", category_level1: "门安装条", quantity: 1, unit_price: 20, unit: "根" },
    ];
    item.quick = { base_price: 1000, attachment_fee: 200, total_cost: 1200 };
    item.formula = {
      material_cost: 400, auxiliary_cost: 100, labor_cost: 200,
      spray_cost: 80, management_fee: 26, attachment_fee: 200, total_cost: 1006,
    };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    const quickSheet = workbook.getWorksheet("快速报价单");
    const headerIndex = (label) => quickSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(quickSheet.getCell("F11").value, 1150, "quick per-cabinet unit total with original-price door strip");
    closeTo(quickSheet.getCell("G11").value, 3450, "quick quote line total with original-price door strip");
    closeTo(quickSheet.getCell("K11").value.result, 1150, "quick cost formula keeps door strip outside discount");
    closeTo(quickSheet.getCell("L11").value, 1000, "quick per-cabinet cabinet amount");
    closeTo(
      quickSheet.getCell("G11").value,
      quickSheet.getCell("F11").value * quickSheet.getCell("D11").value,
      "quick total equals unit price times cabinet quantity",
    );
    closeTo(quickSheet.getCell(11, headerIndex("标准安装板")).value, -100, "negative board per-cabinet amount");
    closeTo(quickSheet.getCell(11, headerIndex("侧板")).value, 100, "side-panel manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("KA2206风机")).value, 30, "fan manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("JS、JP后背板改为单开门")).value, 150, "door-transform manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("门安装条")).value, 20, "door strip original-price amount");
    closeTo(quickSheet.getCell(11, headerIndex("运费")).value, 150, "quick final freight");
    assert.match(
      quickSheet.getCell("K11").value.formula,
      new RegExp(`${quickSheet.getColumn(headerIndex("运费")).letter}11/3`),
    );

    const formulaSheet = workbook.getWorksheet("公式法报价单");
    closeTo(formulaSheet.getCell("F11").value, 957.4, "formula unit keeps door strip outside discount");
    closeTo(formulaSheet.getCell("G11").value, 2872.2, "formula line keeps door strip outside discount");
    closeTo(formulaSheet.getCell("AB11").value, 150, "formula final freight");
    [360, 90, 180, 72, 23.4].forEach((expected, index) => closeTo(
      formulaSheet.getCell(11, 12 + index).value,
      expected,
      `non-ganged formula per-cabinet component ${index + 1}`,
    ));
    closeTo(
      formulaSheet.getCell("G11").value,
      formulaSheet.getCell("F11").value * formulaSheet.getCell("D11").value,
      "formula total equals unit price times cabinet quantity",
    );

    const detailSheet = workbook.getWorksheet("成本明细");
    const quantityByName = new Map();
    let doorStripNote = "";
    detailSheet.eachRow((row) => {
      const name = row.getCell(5).text;
      if (name) quantityByName.set(name, Number(row.getCell(8).value));
      if (name === "门安装条") doorStripNote = row.getCell(15).text;
    });
    assert.equal(quantityByName.get("标准安装板"), 3);
    assert.equal(quantityByName.get("侧板"), 2);
    assert.equal(quantityByName.get("KA2206风机"), 1);
    assert.equal(quantityByName.get("JS、JP后背板改为单开门"), 1);
    assert.equal(quantityByName.get("门安装条"), 3);
    assert.match(doorStripNote, /不参与公式法或快速报价折扣/);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("ganged cabinet stays on one quote row and applies split and order multipliers", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-ganged-cabinet-"));
  const inputPath = path.join(tempDir, "ganged-cabinet.json");
  const outputPath = path.join(tempDir, "ganged-cabinet.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.model_code = "（200+200+200）×600×（600+200）";
    item.specification = item.model_code;
    item.width_mm = 200;
    item.depth_mm = 600;
    item.height_mm = 600;
    item.quantity = 2;
    item.freight_fee = 50;
    item.ganged_cabinet_count = 3;
    item.ganged_cabinets = [0, 1, 2].map((index) => ({
      width_mm: 200, depth_mm: 600, height_mm: 600, base_height_mm: 200,
      single_door_count: index === 0 ? 1 : 0,
      double_door_count: index === 0 ? 0 : 1,
    }));
    item.formula_discount = 0.9;
    item.quick_discount = 0.9;
    item.attachments = [
      { item_name: "固定底座100高", category_level1: "底座", quantity: 1, unit_price: 40, ganged_fixed_base_match: true, ganged_fixed_base_index: 0 },
      { item_name: "固定底座100高", category_level1: "底座", quantity: 1, unit_price: 40, ganged_fixed_base_match: true, ganged_fixed_base_index: 1 },
      { item_name: "固定底座100高", category_level1: "底座", quantity: 1, unit_price: 40, ganged_fixed_base_match: true, ganged_fixed_base_index: 2 },
      { item_name: "标准安装板", category_level1: "安装板", quantity: 1, unit_price: 100, attachment_price_sign: -1 },
      { item_name: "侧板", category_level1: "侧板", quantity: 2, unit_price: 50 },
      { item_name: "KA2206风机", category_level1: "风机滤网", quantity: 1, unit_price: 30 },
      { item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1, unit_price: 150 },
    ];
    item.quick = { base_price: 2000, attachment_fee: 300, total_cost: 2300 };
    item.formula = {
      material_cost: 400, auxiliary_cost: 100, labor_cost: 200,
      spray_cost: 80, management_fee: 26, attachment_fee: 300, total_cost: 1106,
    };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    for (const sheetName of ["公式法报价单", "快速报价单"]) {
      const sheet = workbook.getWorksheet(sheetName);
      assert.equal(sheet.getCell("C11").text, item.specification);
      assert.equal(sheet.getCell("D11").value, 2);
      assert.equal(sheet.getCell("A12").value, null, `${sheetName} split into extra public rows`);
    }
    const quickSheet = workbook.getWorksheet("快速报价单");
    const headerIndex = (label) => quickSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(quickSheet.getCell("F11").value, 2138, "ganged quick equivalent unit total with freight");
    closeTo(quickSheet.getCell("G11").value, 4276, "ganged quick line total with freight");
    closeTo(quickSheet.getCell("L11").value, 4000, "ganged quick cabinet order amount");
    closeTo(quickSheet.getCell("K11").value.result, 4276, "ganged quick order formula result with freight");
    closeTo(quickSheet.getCell(11, headerIndex("固定底座100高")).value, 240, "separately matched ganged base amount");
    closeTo(quickSheet.getCell(11, headerIndex("标准安装板")).value, -200, "ganged board amount");
    closeTo(quickSheet.getCell(11, headerIndex("侧板")).value, 200, "ganged side amount");
    closeTo(quickSheet.getCell(11, headerIndex("KA2206风机")).value, 60, "ganged fan amount");
    closeTo(quickSheet.getCell(11, headerIndex("JS、JP后背板改为单开门")).value, 300, "ganged transform amount");
    closeTo(quickSheet.getCell(11, headerIndex("运费")).value, 100, "ganged freight ignores split count");

    const formulaSheet = workbook.getWorksheet("公式法报价单");
    closeTo(formulaSheet.getCell("F11").value, 1045.4, "ganged formula equivalent unit total with freight");
    closeTo(formulaSheet.getCell("G11").value, 2090.8, "ganged formula line total with freight");
    closeTo(formulaSheet.getCell("AB11").value, 100, "ganged formula freight ignores split count");
    [720, 180, 360, 144, 46.8].forEach((expected, index) => closeTo(
      formulaSheet.getCell(11, 12 + index).value,
      expected,
      `ganged formula component ${index + 1}`,
    ));

    const detailSheet = workbook.getWorksheet("成本明细");
    const quantityByName = new Map();
    let gangedBaseQuantity = 0;
    detailSheet.eachRow((row) => {
      const name = row.getCell(5).text;
      if (name) quantityByName.set(name, Number(row.getCell(8).value));
      if (name === "固定底座100高") gangedBaseQuantity += Number(row.getCell(8).value);
    });
    assert.equal(gangedBaseQuantity, 6);
    assert.equal(quantityByName.get("标准安装板"), 2);
    assert.equal(quantityByName.get("侧板"), 4);
    assert.equal(quantityByName.get("KA2206风机"), 2);
    assert.equal(quantityByName.get("JS、JP后背板改为单开门"), 2);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("formula export falls back from null attachment fees and leaves missing weight or area unrendered", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-null-cost-detail-"));
  const inputPath = path.join(tempDir, "null-cost-detail.json");
  const outputPath = path.join(tempDir, "null-cost-detail.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.quantity = 1;
    item.formula.attachment_fee = null;
    item.formula.corrected_material_weight_kg = null;
    item.formula.material_unit_price = null;
    item.formula.product_area_m2 = null;
    item.formula.spray_unit_price = null;
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    const formulaSheet = workbook.getWorksheet("公式法报价单");
    closeTo(formulaSheet.getCell("F11").value, 755.1, "formula null attachment fee fallback");

    const detailSheet = workbook.getWorksheet("成本明细");
    let materialRow = null;
    let sprayRow = null;
    detailSheet.eachRow((row) => {
      if (row.getCell(4).text === "材料成本") materialRow = row;
      if (row.getCell(4).text === "喷塑费用") sprayRow = row;
    });
    assert.ok(materialRow, "material detail row is missing");
    assert.equal(materialRow.getCell(8).text, "", "null material weight was displayed as zero");
    assert.equal(materialRow.getCell(10).text, "", "null material unit price was displayed as zero");
    assert.ok(sprayRow, "spray detail row is missing");
    assert.match(sprayRow.getCell(5).text, /经验值/);
    assert.equal(sprayRow.getCell(9).text, "项", "null spray area was displayed as square metres");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
