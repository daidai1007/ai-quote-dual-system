import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";
import ExcelJS from "@excel.js/exceljs";
import {projectQuotationAudit} from "./quotation_layout_reader.mjs";
import {money, moneySum, moneyProduct, quickOrderLineBreakdown, PRICING_BASIS, formulaAttachmentLineAmount, attachmentExcludedFromDiscount} from "../quick_discount_rules.mjs";

const amountValue = cell => cell.value?.formula ? (cell.value.result ?? 0) : cell.value;

const projectRoot = path.resolve(import.meta.dirname, "..");
const fixturePath = path.join(projectRoot, "tests", "fixtures", "export_formula_cost_detail.json");
const doorMatrixFixturePath = path.join(projectRoot, "tests", "fixtures", "export_quick_door_matrix.json");
const exporterPath = path.join(projectRoot, "export_dual_quote_workbook.mjs");

const runExporter = async (outputPath, sourcePath = fixturePath) => {
 const request = JSON.parse(await fs.readFile(sourcePath, 'utf8'));
 request.quotation_detail_layout = 'right_vertical_v1';
 const inputPath = outputPath + '.input.json';
 await fs.writeFile(inputPath, JSON.stringify(request));
 return new Promise((resolve, reject) => {
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
};

test("customer metadata survives legacy payload and Excel serialization", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-customer-"));
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    payload.company_name = "任务A测试客户（原下单公司名称）";
    const inputPath = path.join(tempDir, "customer.json");
    const outputPath = path.join(tempDir, "customer.xlsx");
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    for (const name of ["成本", "报价"]) {
      assert.equal(workbook.getWorksheet(name).getCell("B4").value, payload.company_name);
    }
    const detail = workbook.getWorksheet("成本明细");
    assert.equal(amountValue(detail.getCell("G2")), "客户");
    assert.equal(detail.getCell("H2").value, payload.company_name);
  } finally {
    await fs.rm(tempDir, {recursive: true, force: true});
  }
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
      // Deliberately stale lower-priority variant metadata and a SINGLE quick
      // database match prove that exported door wording comes from the current
      // UI counts, not from the quick-quote record.
      variant_code: "SINGLE",
      variant_name: "数据库记录：单门",
      single_door_count: single,
      double_door_count: double,
      quick: {
        ...structuredClone(base.quick),
        matched_experience: {
          ...(base.quick?.matched_experience || {}),
          product_code: "JS_SINGLE",
        },
      },
      final_remark: staleRemark,
      notes: staleRemark,
      source_ocr_remark: staleRemark,
    }));
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    for (const sheetName of ["成本", "报价"]) {
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
  actual = actual?.formula ? (actual.result ?? 0) : actual;
  assert.ok(Number.isFinite(Number(actual)), `${label} is not numeric: ${actual}`);
  assert.ok(Math.abs(Number(actual) - expected) < 0.01, `${label}: expected ${expected}, got ${actual}`);
};
const expectedCurrentFormulaUnit = item => {
  const rows=item.attachments||[];
  const cabinet=moneySum(['material_cost','auxiliary_cost','labor_cost','spray_cost'].map(key=>item.formula[key]));
  const fee=moneyProduct(moneySum([cabinet,...rows.map(formulaAttachmentLineAmount),item.freight_fee||0]),.06);
  return moneySum([moneyProduct(moneySum([cabinet,fee,...rows.filter(row=>!attachmentExcludedFromDiscount(row)).map(formulaAttachmentLineAmount)]),item.formula_discount??1),
    ...rows.filter(attachmentExcludedFromDiscount).map(formulaAttachmentLineAmount),item.freight_fee||0]);
};

// Recalculate the generated arithmetic formulas instead of trusting cached
// XLSX results. Only cell references, arithmetic and ROUND are accepted.
const recalculateQuoteFormula = (sheet, cell) => {
  const value = sheet.getCell(cell).value;
  if (typeof value !== "object" || !value?.formula) return Number(value || 0);
  let expression = value.formula.replace(/\b[A-Z]+\d+\b/g,
    reference => String(recalculateQuoteFormula(sheet, reference)));
  assert.match(expression, /^[\d\s.eE+*/(),\-ROUND]+$/);
  return Function("ROUND", `"use strict"; return (${expression});`)(
    (number, places) => { assert.equal(places, 2); return money(number); },
  );
};

for (const modern of [false, true]) {
  test(modern ? "current ordinary and ganged UI snapshots keep cent-rounded unit times quantity in Excel"
    : "legacy public amounts stay intact and ganged compatibility formulas retain their baseline", async () => {
    const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-unit-rounding-"));
    try {
      const cases = JSON.parse(await fs.readFile(new URL("./fixtures/quote_unit_rounding.json", import.meta.url), "utf8"));
      const payload = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
      payload.items = cases.map(sample => {
        const attachments = [];
        if (sample.eligible) attachments.push({item_name:"安装板",category_level1:"安装板",quantity:1,
          quick_amount:sample.eligible,formula_amount:sample.eligible});
        if (sample.original) attachments.push({item_name:"其他附件",category_level1:"其他附件",quantity:1,
          quick_amount:sample.original,formula_amount:sample.original});
        const fee = money((sample.eligible || 0) + (sample.original || 0));
        const item = {...structuredClone(payload.items[0]), name:sample.name,
          quantity:sample.quantity, quick_discount:sample.discount, formula_discount:sample.discount,
          freight_fee:sample.freight, attachments, ganged_cabinet_count:sample.ganged || 1,
          quick:{base_price:sample.base,attachment_fee:fee,total_cost:money(sample.base+fee)},
          formula:{material_cost:sample.base,auxiliary_cost:0,labor_cost:0,spray_cost:0,management_fee:0,
            attachment_fee:fee,total_cost:money(sample.base+fee)},
        };
        const line = quickOrderLineBreakdown({quote:item.quick,attachments,discount:sample.discount,
          cabinetQuantity:sample.quantity,gangedCabinetCount:sample.ganged || 1,freightFee:sample.freight});
        assert.equal(line.equivalentUnitTotal, sample.unit, sample.name);
        assert.equal(line.lineTotal, sample.total, sample.name);
        if (modern) {
          item.pricing_basis = PRICING_BASIS;
          item.quote_display = {name:item.name,specification:"1000*600*2000",quantity:sample.quantity,unit:"台",
            unit_price:sample.unit,total:sample.total,discount:sample.discount,attachments,
            attachment_face_price:fee,material_difference:0,quick_base_price:sample.base,
            quick_attachment_fee:fee,quick_total_cost:item.quick.total_cost};
        }
        return item;
      });
      const inputPath = path.join(tempDir,"rounding.json");
      const outputPath = path.join(tempDir,"rounding.xlsx");
      await fs.writeFile(inputPath,JSON.stringify(payload),"utf8");
      await runExporter(outputPath,inputPath);
      const workbook = new ExcelJS.Workbook();
      await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
      for (const name of ["成本","报价"]) {
        const sheet = workbook.getWorksheet(name);
        cases.forEach((sample,index) => {
          const row = 11 + index;
          const unit=name==='成本'?expectedCurrentFormulaUnit(payload.items[index]):sample.unit;
          const total=moneyProduct(unit,sample.quantity);
          assert.equal(sheet.getCell(`F${row}`).value,unit,`${name} ${sample.name} unit`);
          assert.equal(amountValue(sheet.getCell(`G${row}`)),total,`${name} ${sample.name} total`);
          assert.equal(moneyProduct(sheet.getCell(`F${row}`).value,sample.quantity),total);
          const freightColumn = sheet.getRow(10).values.indexOf("运费");
          assert.ok(freightColumn > 0, `${name} freight column`);
          assert.equal(money(sheet.getCell(row,freightColumn).value || 0),
            moneyProduct(sample.freight,modern ? 1 : sample.quantity), `${sample.name} undiscounted freight`);
          if (name === "报价") {
            if (!modern && sample.ganged > 1) {
              // Frozen baseline from before the rounding task: this separate
              // historical branch is not part of current per-set exports.
              assert.equal(sheet.getCell(`J${row}`).value.formula,
                sample.legacy_original_formula.replaceAll("{row}",String(row)));
              assert.equal(sheet.getCell(`K${row}`).value.formula,
                sample.legacy_discounted_formula.replaceAll("{row}",String(row)));
              assert.equal(sheet.getCell(`K${row}`).value.result,sample.unit);
            } else {
              const expectedK = modern ? moneyProduct(sheet.getCell(`J${row}`).value.result,sample.quantity) : sample.unit;
              assert.equal(recalculateQuoteFormula(sheet,`K${row}`),expectedK,`${sample.name} Excel recalculation`);
              assert.equal(sheet.getCell(`K${row}`).value.result,expectedK);
              if (modern) {
                assert.doesNotMatch(sheet.getCell(`J${row}`).value.formula,/\/D\d+/);
                assert.equal(sheet.getCell(`K${row}`).value.formula,`ROUND(J${row}*D${row},2)`);
              }
            }
          }
        });
        assert.equal(amountValue(sheet.getCell(`G${11+cases.length}`)),moneySum(cases.map((sample,index)=>
          name==='成本'?moneyProduct(expectedCurrentFormulaUnit(payload.items[index]),sample.quantity):sample.total)));
      }
    } finally {
      await fs.rm(tempDir,{recursive:true,force:true});
    }
  });
}

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

test("quick public quote uses the click-time UI snapshot verbatim", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-ui-snapshot-"));
  const inputPath = path.join(tempDir, "quote-ui-snapshot.json");
  const outputPath = path.join(tempDir, "quote-ui-snapshot.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.name = "人工名称";
    item.attachments = [{
      item_name: "铜排", quantity: 1, catalog_version: "server-v2",
      quick_amount: 50, unit_price_override: 50, formula_amount: 8.1, status: "OK",
    }];
    item.quick = { ...item.quick, attachment_fee: 50 };
    item.quote_display = {
      name: "人工名称",
      specification: "600*230*400",
      quantity: 1,
      unit: "台",
      unit_price: 448.44,
      discount: 0.8,
      total: 448.44,
      remark: "人工备注。",
      attachments: [{
        item_name: "铜排", quantity: 1, catalog_version: "client-v2",
        quick_amount: 15, quick_amount_override: 15,
        unit_price_override: 15, formula_amount: 8.1, status: "OK",
        custom_amount_edited: true,
      }],
      quick_total_cost: 560,
      quick_attachment_fee: 15,
      quick_base_price: 545,
    };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    const quickSheet = workbook.getWorksheet("报价");
    assert.deepEqual(
      [2, 3, 4, 5, 6, 7, 8].map((column) => amountValue(quickSheet.getCell(11, column))),
      ["人工名称", "600*230*400", 1, "台", 448.44, 448.44, "人工备注。"],
    );
    const headers = quickSheet.getRow(10).values;
    const discountColumn = headers.findIndex((value) => value === "折扣");
    assert.equal(quickSheet.getCell(11, discountColumn).value, 0.8);
    const copperColumn = headers.findIndex((value) => value === "铜排");
    assert.ok(copperColumn > 0, "铜排 audit column is missing");
    assert.equal(quickSheet.getCell(11, copperColumn).value, 15);
    assert.equal(headers.includes("其他附件/差额"), false);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("both quotation sheets preserve cleared and multiline manual remarks", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-manual-remarks-"));
  try {
    for (const [index, remark] of ["", "人工备注 <A>&B\n第二行说明"].entries()) {
      const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
      const item = payload.items[0];
      for (const key of ["final_remark", "notes", "source_ocr_remark", "source_reviewed_remark"]) item[key] = remark;
      item.quote_remark_manual = true;
      item.quote_display = {name:"合成备注测试柜",specification:"600*230*400",quantity:1,unit:"台",
        unit_price:448.44,total:448.44,discount:0.8,remark};
      payload.items = [item];
      const inputPath = path.join(tempDir, `input-${index}.json`);
      const outputPath = path.join(tempDir, `output-${index}.xlsx`);
      await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
      await runExporter(outputPath, inputPath);
      const workbook = new ExcelJS.Workbook();
      await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
      for (const sheetName of ["成本", "报价"]) {
        assert.equal(String(workbook.getWorksheet(sheetName).getCell("H11").value ?? ""), remark);
      }
    }
  } finally {
    await fs.rm(tempDir, {recursive:true,force:true});
  }
});

test("ganged quick export keeps the click-time attachment amount", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-ganged-ui-snapshot-"));
  const inputPath = path.join(tempDir, "ganged-ui-snapshot.json");
  const outputPath = path.join(tempDir, "ganged-ui-snapshot.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.quantity = 1;
    item.ganged_cabinet_count = 3;
    item.ganged_cabinets = [{}, {}, {}];
    item.attachments = [{
      item_name: "风机SG22060HA2/220V（国产）", quantity: 4,
      catalog_version: "client-v2", quick_amount: 480,
      unit_price_override: 120, formula_amount: 280, status: "FIXED",
    }];
    item.quick = { base_price: 1000, attachment_fee: 480, total_cost: 1480 };
    item.quote_display = {
      name: "并柜报价", specification: "900+900+1400*800*(2200+200)",
      quantity: 1, unit: "台", unit_price: 1480, discount: 1, total: 1480,
      remark: "并柜报价。",
      attachments: [{
        item_name: "风机SG22060HA2/220V（国产）", quantity: 4,
        catalog_version: "client-v2", quick_amount: 480,
        unit_price_override: 120, formula_amount: 280, status: "FIXED",
      }],
      quick_total_cost: 1480, quick_attachment_fee: 480, quick_base_price: 1000,
    };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    const quickSheet = workbook.getWorksheet("报价");
    const headers = quickSheet.getRow(10).values;
    const fanColumn = headers.findIndex((value) => value === "风机SG22060HA2/220V（国产）");
    assert.ok(fanColumn > 0, "ganged fan audit column is missing");
    closeTo(quickSheet.getCell(11, fanColumn).value, 480, "ganged click-time fan amount");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("formula quotation mirrors quick attachment-name detail columns", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-formula-attachment-columns-"));
  const inputPath = path.join(tempDir, "formula-attachment-columns.json");
  const outputPath = path.join(tempDir, "formula-attachment-columns.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(fixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.formula_discount = 1;
    item.attachments = [
      { item_name: "A4资料盒", quantity: 2, unit_price: 20 },
      {
        item_name: "平面锁改为MS830锁", quantity: 6, formula_amount: 132,
        quick_amount: 300, catalog_version: "server-v2", status: "FIXED",
      },
    ];
    item.formula = {
      material_cost: 100, auxiliary_cost: 50, labor_cost: 20,
      spray_cost: 10, management_fee: 5, attachment_fee: 172, total_cost: 357,
    };
    item.quick = { base_price: 300, attachment_fee: 340, total_cost: 640 };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    const formulaSheet = workbook.getWorksheet("成本");
    const quickSheet = workbook.getWorksheet("报价");
    const formulaHeaderIndex = (label) => formulaSheet.getRow(10).values.findIndex((value) => value === label);
    const quickHeaderIndex = (label) => quickSheet.getRow(10).values.findIndex((value) => value === label);
    for (const name of ["A4资料盒", "平面锁改为MS830锁"]) {
      assert.ok(formulaHeaderIndex(name) > 0, `formula ${name} column is missing`);
      assert.ok(quickHeaderIndex(name) > 0, `quick ${name} column is missing`);
    }
    closeTo(formulaSheet.getCell(11, formulaHeaderIndex("A4资料盒")).value, 40, "formula A4 document-box cost");
    closeTo(formulaSheet.getCell(11, formulaHeaderIndex("平面锁改为MS830锁")).value, 132, "formula MS830 lock cost");
    closeTo(quickSheet.getCell(11, quickHeaderIndex("A4资料盒")).value, 40, "quick A4 document-box amount");
    closeTo(quickSheet.getCell(11, quickHeaderIndex("平面锁改为MS830锁")).value, 300, "quick MS830 lock amount");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

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
        material_cost: 10,
        spray_cost: 5,
        auxiliary_cost: 4,
        labor_cost: 6,
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
    projectQuotationAudit(workbook);
    const formulaSheet = workbook.getWorksheet("成本");
    const quickSheet = workbook.getWorksheet("报价");
    const formulaHeaderIndex = (label) => formulaSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(formulaSheet.getCell(11, formulaHeaderIndex("门限位器")).value, 90, "formula limiter per-cabinet amount after discount");
    const limiterColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门限位器");
    assert.ok(limiterColumn > 0, "quick limiter name column is missing");
    closeTo(quickSheet.getCell(11, limiterColumn).value, 100, "quick limiter per-cabinet amount");
    const reinforcementColumn = quickSheet.getRow(10).values.findIndex((value) => value === "门加强筋");
    assert.ok(reinforcementColumn > 0, "quick reinforcement name column is missing");
    closeTo(quickSheet.getCell(11, reinforcementColumn).value, 120, "quick reinforcement per-cabinet amount");
    assert.deepEqual(
      ["L11", "M11", "N11", "O11", "P11"].map((cell) => Number(formulaSheet.getCell(cell).value)),
      [180, 90, 270, 135, 52.38],
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
    assert.match(limiterRow.getCell(7).text,
      /单位成本＝材料成本 10\.00 \+ 喷塑成本 5\.00 \+ 辅材 4\.00 \+ 人工 6\.00 = 25\.00 元/);
    assert.ok(reinforcementRow, "door reinforcement BOM row is missing");
    closeTo(reinforcementRow.getCell(8).value, 8, "door reinforcement BOM final quantity");
    closeTo(reinforcementRow.getCell(10).value, 30, "door reinforcement BOM unit price");
    closeTo(reinforcementRow.getCell(11).value, 240, "door reinforcement BOM amount");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("formal workbook preserves the legacy desktop quotation format", async () => {
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
    projectQuotationAudit(workbook);
    assert.deepEqual(workbook.worksheets.map((sheet) => sheet.name), [
      "成本", "报价", "成本明细",
    ]);

    const expectedSeller = [
      "浙江京能电力设备有限公司",
      "杭州临安横畈工业功能区桑园路18号",
      "0571-88520091",
      "0571-88520077",
      "",
    ];
    for (const [sheetName, expectedAmounts] of [
      ["成本", (JSON.parse(await fs.readFile(fixturePath,'utf8')).items).map(item=>{
        const unit=expectedCurrentFormulaUnit(item);return [unit,moneyProduct(unit,item.quantity)];
      })],
      ["报价", [[3200, 6400], [4100, 4100]]],
    ]) {
      const sheet = workbook.getWorksheet(sheetName);
      assert.equal(sheet.getCell("F10").text, sheetName === "报价" ? "折后单价" : "单价");
      assert.equal(sheet.getCell("G10").text, sheetName === "报价" ? "折后总价" : "总价");
      assert.deepEqual([4, 5, 6, 7, 8].map((row) => sheet.getCell(row, 6).text), expectedSeller);
      expectedAmounts.forEach(([unitPrice, totalPrice], index) => {
        closeTo(sheet.getCell(11 + index, 6).value, unitPrice, `${sheetName} unit price row ${11 + index}`);
        closeTo(sheet.getCell(11 + index, 7).value, totalPrice, `${sheetName} total price row ${11 + index}`);
      });
    }

    const quickSheet = workbook.getWorksheet("报价");
    assert.equal(quickSheet.getCell("J10").text, "原价单价");
    assert.equal(quickSheet.getCell("K10").text, "折后单价");
    closeTo(quickSheet.getCell("J11").value.result, 3200, "quick original unit formula cached result");
    const quickFormulaCell = quickSheet.getCell("K11");
    const discountColumn = quickSheet.getRow(10).values.findIndex(
      (value) => value === "折扣",
    );
    assert.equal(
      quickFormulaCell.value.formula,
      `ROUND(ROUND(L11*${quickSheet.getColumn(discountColumn).letter}11,2)+M11+N11,2)`,
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
    projectQuotationAudit(workbook);
    await reversedWorkbook.xlsx.readFile(reversedOutputPath);
    projectQuotationAudit(reversedWorkbook);
    const sheet = workbook.getWorksheet("报价");
    const reversedSheet = reversedWorkbook.getWorksheet("报价");
    const formulaSheet = workbook.getWorksheet("成本");
    const headers = sheet.getRow(10).values.slice(10).filter((value) => value !== null && value !== undefined && value !== "");
    const reversedHeaders = reversedSheet.getRow(10).values.slice(10).filter((value) => value !== null && value !== undefined && value !== "");
    assert.deepEqual(headers, reversedHeaders, "dynamic attachment order changed with quote row order");
    assert.deepEqual(headers.slice(0, 3), ["原价单价", "折后单价", "柜体"]);
    assert.deepEqual(headers.slice(-2), ["运费", "折扣"]);
    assert.ok(!headers.includes("其他附件/差额"));
    assert.ok(!headers.includes("配置变形说明"));
    assert.ok(!headers.includes("配置变形"));
    const dynamicNames = headers.slice(3, -2);
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
      const originalBreakdown = [1100, 1050, 1260, 1770, 1400, 2180][index];
      closeTo(sheet.getCell(row, 10).value.result, originalBreakdown, `door matrix original total row ${row}`);
      closeTo(sheet.getCell(row, 6).value, unitTotal, `door matrix quick unit total row ${row}`);
      closeTo(sheet.getCell(row, 7).value, lineTotal, `door matrix quick line total row ${row}`);
      const formula = sheet.getCell(row, 11).value.formula;
      assert.match(formula, new RegExp(`${sheet.getColumn(discountColumn).letter}${row}`));
    });
    const boardColumn = headerIndex("标准安装板");
    assert.equal(sheet.getCell(12, boardColumn).value, -100);
    assert.match(sheet.getCell(12, 11).value.formula, new RegExp(`${sheet.getColumn(boardColumn).letter}12`));
    const formulaBoardColumn = formulaSheet.getRow(10).values.findIndex((value) => value === "标准安装板");
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

test("quick workbook uses popup attachment rows and omits synthetic fee deltas", async () => {
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
    projectQuotationAudit(workbook);
    const sheet = workbook.getWorksheet("报价");
    const headers = sheet.getRow(10).values;
    const otherColumn = headers.findIndex((value) => value === "其他附件/差额");
    const discountColumn = headers.findIndex((value) => value === "折扣");
    assert.equal(otherColumn, -1);
    assert.equal(headers.includes("配置变形说明"), false);
    assert.equal(headers.includes("配置变形"), false);
    assert.equal(sheet.getCell(11, 11).value.formula, `ROUND(ROUND((L11+M11)*${sheet.getColumn(discountColumn).letter}11,2),2)`);
    closeTo(sheet.getCell(11, 6).value, 990, "popup attachment row total");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test("workbook uses final attachment quantities for every ordinary row", async () => {
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
    projectQuotationAudit(workbook);
    const quickSheet = workbook.getWorksheet("报价");
    const headerIndex = (label) => quickSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(quickSheet.getCell("F11").value, 1150, "quick per-cabinet unit total with original-price door strip");
    closeTo(amountValue(quickSheet.getCell("G11")), 3450, "quick quote line total with original-price door strip");
    closeTo(quickSheet.getCell("K11").value.result, 1150, "quick cost formula keeps door strip outside discount");
    closeTo(quickSheet.getCell("L11").value, 1000, "quick per-cabinet cabinet amount");
    closeTo(
      amountValue(quickSheet.getCell("G11")),
      quickSheet.getCell("F11").value * quickSheet.getCell("D11").value,
      "quick total equals unit price times cabinet quantity",
    );
    closeTo(quickSheet.getCell(11, headerIndex("标准安装板")).value, -100, "negative board per-cabinet amount");
    closeTo(quickSheet.getCell(11, headerIndex("侧板")).value, 100, "side-panel manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("KA2206风机")).value, 30, "fan manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("JS、JP后背板改为单开门")).value, 150, "door-transform manual amount");
    closeTo(quickSheet.getCell(11, headerIndex("门安装条")).value, 20, "door strip original-price amount");
    closeTo(quickSheet.getCell(11, headerIndex("运费")).value, 150, "quick final freight");
    assert.equal(recalculateQuoteFormula(quickSheet,"K11"),1150,
      "Excel recalculation preserves the rounded unit price with freight outside discount");

    const formulaSheet = workbook.getWorksheet("成本");
    closeTo(formulaSheet.getCell("F11").value, 854.62, "formula unit scales ordinary attachment rows");
    closeTo(amountValue(formulaSheet.getCell("G11")), 2563.86, "formula line scales ordinary attachment rows");
    const formulaHeaderIndex = (label) => formulaSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(formulaSheet.getCell(11, formulaHeaderIndex("运费")).value, 150, "formula final freight");
    [360, 90, 180, 72, 55.62].forEach((expected, index) => closeTo(
      formulaSheet.getCell(11, 12 + index).value,
      expected,
      `non-ganged formula per-cabinet component ${index + 1}`,
    ));
    closeTo(
      amountValue(formulaSheet.getCell("G11")),
      formulaSheet.getCell("F11").value * formulaSheet.getCell("D11").value,
      "formula total equals unit price times cabinet quantity",
    );

    const detailSheet = workbook.getWorksheet("成本明细");
    const quantityByName = new Map();
    let doorStripNote = "";
    let doorTransformationAmount = null;
    let doorTransformationNote = "";
    detailSheet.eachRow((row) => {
      const name = row.getCell(5).text;
      if (name) quantityByName.set(name, Number(row.getCell(8).value));
      if (name === "门安装条") doorStripNote = row.getCell(15).text;
      if (name === "JS、JP后背板改为单开门") {
        doorTransformationAmount = Number(row.getCell(11).value);
        doorTransformationNote = row.getCell(15).text;
      }
    });
    assert.equal(quantityByName.get("标准安装板"), 3);
    assert.equal(quantityByName.get("侧板"), 6);
    assert.equal(quantityByName.get("KA2206风机"), 3);
    assert.equal(quantityByName.get("JS、JP后背板改为单开门"), 3);
    assert.equal(quantityByName.get("门安装条"), 3);
    assert.match(doorStripNote, /不参与公式法或快速报价折扣/);
    assert.equal(doorTransformationAmount, 0);
    assert.match(doorTransformationNote, /仅快速报价计费；公式法附件费用为 0/);
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
    projectQuotationAudit(workbook);
    for (const sheetName of ["成本", "报价"]) {
      const sheet = workbook.getWorksheet(sheetName);
      assert.equal(sheet.getCell("C11").text, item.specification);
      assert.equal(sheet.getCell("D11").value, 2);
      assert.equal(sheet.getCell("A12").value, null, `${sheetName} split into extra public rows`);
    }
    const quickSheet = workbook.getWorksheet("报价");
    const headerIndex = (label) => quickSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(quickSheet.getCell("F11").value, 2138, "ganged quick equivalent unit total with freight");
    closeTo(amountValue(quickSheet.getCell("G11")), 4276, "ganged quick line total with freight");
    closeTo(quickSheet.getCell("J11").value.result, 2350, "ganged quick original unit price");
    closeTo(quickSheet.getCell("L11").value, 4000, "ganged quick cabinet order amount");
    closeTo(quickSheet.getCell("K11").value.result, 2138, "ganged quick discounted unit formula result with freight");
    closeTo(quickSheet.getCell(11, headerIndex("固定底座100高")).value, 240, "separately matched ganged base amount");
    closeTo(quickSheet.getCell(11, headerIndex("标准安装板")).value, -200, "ganged board amount");
    closeTo(quickSheet.getCell(11, headerIndex("侧板")).value, 200, "ganged side amount");
    closeTo(quickSheet.getCell(11, headerIndex("KA2206风机")).value, 60, "ganged fan amount");
    closeTo(quickSheet.getCell(11, headerIndex("JS、JP后背板改为单开门")).value, 300, "ganged transform amount");
    closeTo(quickSheet.getCell(11, headerIndex("运费")).value, 100, "ganged freight ignores split count");

    const formulaSheet = workbook.getWorksheet("成本");
    closeTo(formulaSheet.getCell("F11").value, 948.02, "ganged formula equivalent unit excludes door transformation");
    closeTo(amountValue(formulaSheet.getCell("G11")), 1896.04, "ganged formula line excludes door transformation");
    const formulaHeaderIndex = (label) => formulaSheet.getRow(10).values.findIndex((value) => value === label);
    closeTo(formulaSheet.getCell(11, formulaHeaderIndex("运费")).value, 100, "ganged formula freight ignores split count");
    [720, 180, 360, 144, 122.04].forEach((expected, index) => closeTo(
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
    projectQuotationAudit(workbook);
    const formulaSheet = workbook.getWorksheet("成本");
    closeTo(formulaSheet.getCell("F11").value, 763.2, "formula uses popup fee and current management");

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

test("other attachments stay at original price in both exported quotations", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "quote-other-attachment-original-price-"));
  const inputPath = path.join(tempDir, "other-attachment-input.json");
  const outputPath = path.join(tempDir, "other-attachment-output.xlsx");
  try {
    const payload = JSON.parse(await fs.readFile(doorMatrixFixturePath, "utf8"));
    const item = structuredClone(payload.items[0]);
    item.quantity = 1;
    item.freight_fee = 0;
    item.formula_discount = 0.8;
    item.quick_discount = 0.8;
    item.attachments = [{
      item_name: "侧门",
      category_level1: "其他附件",
      quantity: 1,
      unit_price: 150,
      unit: "扇",
    }];
    item.quick = { base_price: 1000, attachment_fee: 150, total_cost: 1150 };
    item.formula = {
      material_cost: 400,
      auxiliary_cost: 200,
      labor_cost: 200,
      spray_cost: 174,
      management_fee: 26,
      attachment_fee: 150,
      total_cost: 1150,
    };
    payload.items = [item];
    await fs.writeFile(inputPath, JSON.stringify(payload), "utf8");
    await runExporter(outputPath, inputPath);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.readFile(outputPath);
    projectQuotationAudit(workbook);
    const formulaSheet = workbook.getWorksheet("成本");
    const quickSheet = workbook.getWorksheet("报价");
    closeTo(formulaSheet.getCell("F11").value, 983.15, "formula keeps other attachment outside discount");
    closeTo(quickSheet.getCell("F11").value, 950, "quick keeps other attachment outside discount");

    const quickHeaders = quickSheet.getRow(10).values;
    const sideDoorColumn = quickHeaders.findIndex((value) => value === "侧门");
    assert.ok(sideDoorColumn > 0, "selected other-attachment column is missing");
    closeTo(quickSheet.getCell(11, sideDoorColumn).value, 150, "other attachment original amount");
    assert.match(
      quickSheet.getCell("K11").value.formula,
      new RegExp(`\\+${quickSheet.getColumn(sideDoorColumn).letter}11`),
    );

    const detailSheet = workbook.getWorksheet("成本明细");
    let sideDoorNote = "";
    detailSheet.eachRow((row) => {
      if (row.getCell(5).text === "侧门") sideDoorNote = row.getCell(15).text;
    });
    assert.match(sideDoorNote, /不参与公式法或快速报价折扣/);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
