/*
 * Formal dual quotation workbook exporter.
 *
 * Input is a confirmed multi-cabinet JSON snapshot.  The reference workbook
 * remains the visual template; this script creates method-specific formula
 * and quick-quote sheets and fills only quote values.  No calculation is
 * performed here.
 */
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: export_dual_quote_workbook.mjs input.json output.xlsx");
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
if (!Array.isArray(payload.items) || payload.items.length === 0) {
  throw new Error("报价清单为空，无法生成正式报价单");
}
const projectRoot = path.dirname(fileURLToPath(import.meta.url));
const templatePath = path.join(projectRoot, "templates", "quote_template.xlsx");
try {
  await fs.access(templatePath);
} catch {
  throw new Error(`找不到正式报价单模板：${templatePath}`);
}
const template = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(template);
const formulaSheet = workbook.worksheets.getItemAt(0);
formulaSheet.name = "公式法报价单";
const quickSheet = workbook.worksheets.add("快速报价单");
quickSheet.getRange("A1:Y20").copyFrom(formulaSheet.getRange("A1:Y20"), "all");
// artifact-tool's current cross-sheet copyFrom("all") copies cell values and
// formulas but does not carry the imported XLSX style index.  Both sheets live
// in the same workbook and therefore share the same style table, so copying
// each cell's styleIndex is the lossless way to preserve borders, fills,
// fonts, alignment and number formats from the reference sheet.
for (let row = 0; row < 20; row += 1) {
  for (let column = 0; column < 25; column += 1) {
    const sourceCell = formulaSheet.__getCell(row, column);
    if (!sourceCell || sourceCell.styleIndex === undefined) continue;
    quickSheet.__getOrCreateCell(row, column).styleIndex = sourceCell.styleIndex;
  }
}

// Cross-sheet copyFrom() also does not reproduce the source worksheet's
// merged cells, column widths or row heights. Apply the fixed template
// geometry explicitly so both quotation sheets have the same layout in
// Excel/WPS.
const templateColumnWidths = {
  A: 4.33333333333333,
  B: 17.2833333333333,
  C: 22.775,
  D: 5.775,
  E: 5.10833333333333,
  F: 9,
  G: 9,
  H: 9,
  I: 9,
  J: 54.4916666666667,
  K: 25.2,
  L: 9.26666666666667,
  M: 9.26666666666667,
  N: 10.05,
  O: 10.725,
  P: 10.725,
  Q: 14.1916666666667,
  R: 10.725,
  S: 11.8833333333333,
  T: 7.225,
  U: 10.1416666666667,
  V: 10.1416666666667,
  W: 10.1416666666667,
  X: 10.1416666666667,
  Y: 9,
};
const templateRowHeights = {
  1: 20.1, 2: 20.1, 3: 22.5,
  4: 16.5, 5: 16.5, 6: 16.5, 7: 16.5, 8: 16.5,
  9: 24.9, 10: 33,
  11: 81, 12: 101, 13: 80, 14: 76, 15: 77, 16: 74,
  17: 118, 18: 90, 19: 19.5, 20: 19.5,
  21: 19.5, 22: 19.5, 23: 19.5, 24: 19.5,
  25: 50.1, 26: 50.1, 27: 50.1, 28: 50.1,
};
const templateMergeRanges = [
  "A1:C2",
  "E1:G1", "E2:G2",
  "B4:D4", "F4:J4",
  "B5:D5", "F5:J5",
  "B6:D6", "F6:J6",
  "B7:D7", "F7:J7",
  "B8:D8", "F8:J8",
];

function applyTemplateGeometry(sheet, applyMerges = false) {
  for (const [column, width] of Object.entries(templateColumnWidths)) {
    sheet.getRange(`${column}1:${column}20`).format.columnWidth = width;
  }
  for (const [row, height] of Object.entries(templateRowHeights)) {
    sheet.getRange(`A${row}:Y${row}`).format.rowHeight = height;
  }
  if (applyMerges) {
    for (const range of templateMergeRanges) sheet.mergeCells(range);
  }
}

const col = (n) => {
  let text = "";
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) text = String.fromCharCode(65 + (x - 1) % 26) + text;
  return text;
};

applyTemplateGeometry(formulaSheet);
applyTemplateGeometry(quickSheet, true);

// The formula sheet exposes its five database cost components before the
// attachment-price columns.  The quick sheet intentionally keeps the original
// fixed template unchanged.  In the formula sheet, replace the old L “柜体”
// column with the five component columns L:P, then move the original attachment
// columns M:Y four places to the right (Q:AC).  Same-sheet copyFrom preserves
// values/formulas; copying styleIndex explicitly also protects formatting when
// artifact-tool imports the source XLSX with indexed styles.
// Source and destination overlap. Move one column at a time from right to
// left so an already-copied destination can never overwrite a source column
// that is still waiting to be moved.
for (let sourceColumn = 25; sourceColumn >= 13; sourceColumn -= 1) {
  const sourceLetter = col(sourceColumn);
  const targetLetter = col(sourceColumn + 4);
  formulaSheet.getRange(`${targetLetter}1:${targetLetter}28`).copyFrom(
    formulaSheet.getRange(`${sourceLetter}1:${sourceLetter}28`),
    "all",
  );
  for (let row = 0; row < 28; row += 1) {
    const sourceCell = formulaSheet.__getCell(row, sourceColumn - 1);
    if (!sourceCell || sourceCell.styleIndex === undefined) continue;
    formulaSheet.__getOrCreateCell(row, sourceColumn + 3).styleIndex = sourceCell.styleIndex;
  }
}
for (let sourceColumn = 13; sourceColumn <= 25; sourceColumn += 1) {
  const sourceLetter = col(sourceColumn);
  const targetLetter = col(sourceColumn + 4);
  formulaSheet.getRange(`${targetLetter}1:${targetLetter}28`).format.columnWidth =
    templateColumnWidths[sourceLetter];
}
formulaSheet.getRange("M1:P28").clear({ applyTo: "contents" });
formulaSheet.getRange("L10:P10").values = [[
  "材料成本", "辅材成本", "人工成本", "喷塑费用", "管理费用",
]];

// Return the one-based Excel column used by the fixed quotation template.
// The attachment price area begins at L (柜体). K is an intentional spacer.
const attachmentColumn = (itemName = "") => {
  const name = String(itemName);
  if (name.includes("柜体")) return 12;
  if (name.includes("底座")) return 13;
  if (name.includes("侧板")) return 14;
  if (name.includes("三排")) return 15;
  if (name.includes("安装板单发")) return 23;
  if (name.includes("填充") || name.includes("安装板")) return 16;
  if (
    name.includes("照明灯")
    || name.includes("柜内灯")
    || name.includes("灯开关")
    || name.includes("行程开关")
    || name.includes("限位开关")
    || name.includes("门开关")
  ) return 17;
  if (name.includes("文件夹")) return 18;
  if (name.includes("风机") || name.includes("过滤网") || name.includes("滤网")) return 19;
  if (name.includes("门限位器") || name === "限位器") return 20;
  if (name.includes("接地")) return 21;
  if (name.includes("双开门")) return 22;
  if (name.includes("运费")) return 24;
  return null;
};

const asNumber = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const fmt = (value) => String(asNumber(value)).replace(/\.0+$/, "");
const drawingNameBeforeChinese = (value) => {
  const stem = path.basename(String(value || "").trim()).replace(/\.pdf$/i, "");
  const firstChinese = stem.search(/[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]/u);
  const prefix = firstChinese >= 0 ? stem.slice(0, firstChinese) : stem;
  return prefix.trim() || stem;
};
const attachmentUnitPrice = (item = {}) => {
  for (const key of ["unit_price_override", "matched_price", "unit_price", "price"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      return Number(item[key]);
    }
  }
  return 0;
};
const attachmentLineAmount = (item = {}) => {
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      return Number(item[key]);
    }
  }
  return attachmentUnitPrice(item) * (asNumber(item.quantity) || 1);
};
const attachmentAmounts = (attachments = [], discount = 1, method = "quick") => {
  const out = {};
  for (const item of attachments) {
    let index = attachmentColumn(item.item_name || item.model_code);
    if (method === "formula") {
      // “柜体” is replaced by formula cost components; all real attachment
      // columns from 底座 onward move four places right on the formula sheet.
      if (index === 12) index = null;
      else if (index >= 13) index += 4;
    }
    if (index) out[index] = (out[index] || 0) + attachmentLineAmount(item) * discount;
  }
  return out;
};
const attachmentTotalFromItems = (attachments = []) =>
  attachments.reduce((sum, item) => sum + attachmentLineAmount(item), 0);

const quantityText = (value) => {
  const number = Number(value ?? 1);
  return Number.isFinite(number) ? String(number) : "1";
};

const attachmentRemark = (item = {}) => {
  const name = String(item.item_name || "").trim();
  const model = String(item.model_code || "").trim();
  const variant = String(item.variant || "").trim();
  const source = String(item.price_source || "").trim();
  const notes = String(item.notes || "").trim();
  const qty = quantityText(item.quantity);
  const combined = [name, model, variant, notes].filter(Boolean).join(" ");
  if (name.includes("安装板")) {
    const thickness = combined.match(/(\d+(?:\.\d+)?)\s*mm/i)?.[1];
    return `配${thickness ? `${thickness}镀锌安装板` : "镀锌安装板"}${qty}块`;
  }
  if (name.includes("侧板")) return `配侧板${qty}块`;
  if (name.includes("背板")) return `配背板${qty}块`;
  if (name.includes("门") && (name.includes("双开") || name.includes("单开"))) return `配${name}${qty}扇`;
  if (name.includes("锁")) {
    const label = model && !name.includes(model) && !model.includes("所有型号")
      ? (model.includes("锁") ? model : `${model}${name}`) : name;
    return `配${label}${qty}件`;
  }
  if (combined.includes("液压") && combined.includes("支撑")) return `配液压支撑杆${qty}件`;
  if (name.includes("文件夹")) return `配${combined.toUpperCase().includes("A4") ? "A4文件夹" : name}${qty}个`;
  if (name.includes("接地")) return `配接地线${qty}套`;
  if (name.includes("底座")) {
    const height = item.height_mm === null || item.height_mm === undefined || item.height_mm === ""
      ? "" : `${Number(item.height_mm)}高`;
    return `配${height}${name.includes("活动") ? "活动底座" : "底座"}${Number(qty) === 1 ? "" : `${qty}件`}`;
  }
  if (name.includes("风机")) {
    const label = (model || name).replace(/风机/g, "").trim();
    const voltage = /220\s*V/i.test(combined) ? "220V" : "";
    const origin = source.includes("国产") ? "国产" : "";
    return `配${voltage}${origin}${label}风机${qty}个`;
  }
  if (name.includes("过滤网") || name.includes("滤网")) {
    const label = (model || name).replace(/过滤网|滤网|FU-/g, "").trim();
    return `配${label}滤网${qty}个`;
  }
  if (name.includes("照明灯") || name.includes("柜内灯")) return `配照明灯${qty}套`;
  if (["行程开关", "灯开关", "限位开关", "门开关"].some((key) => name.includes(key))) return `配${name}${qty}套`;
  if (name.includes("抽屉")) return `配抽屉${qty}件`;
  if (name.includes("把手")) return `配${name}${qty}个`;
  if (name.includes("滑轨")) {
    const length = combined.match(/(\d+)\s*mm/i)?.[1];
    return `配${length ? `${length}mm长滑轨` : name}${qty}套`;
  }
  if (name.includes("三排") || name.includes("纵梁")) return `配三排纵梁${qty}根`;
  if (name.includes("门限位器") || name === "限位器") return `配门限位器${qty}套`;
  return name ? `配${name}${qty}件` : "";
};

// Convert raw OCR technical requirements into the concise configuration
// wording approved for the formal quotation.  This fallback also upgrades
// draft rows created by older client builds at export time.
const standardizedRemark = (item = {}) => {
  const stored = String(item.final_remark || item.notes || "").trim();
  const source = String(item.source_ocr_remark || stored).trim();
  const numbered = /(?:^|\n)\s*\d+[\.、)]/.test(source);
  if (stored && !stored.includes("技术要求") && !numbered) return stored;
  const family = String(item.product_family || item.product_code || "").trim();
  const productCode = String(item.product_code || "").toUpperCase();
  const variant = String(item.variant_name || item.variant_code || "");
  const material = String(item.material_code || "SECC").toUpperCase();
  const coating = String(item.coating_type || "");
  let structure;
  if (productCode === "OP_TABLE_EXP" || family.includes("操作台") || source.includes("斜面操作台")) {
    structure = "斜面操作台结构";
  } else {
    const match = source.match(/仿威图\s*([A-Za-z]{1,8})\s*(箱|柜)/i);
    structure = match ? `仿威图${match[1].toUpperCase()}${match[2]}`
      : `仿威图${family}${["JA", "JE", "JK"].includes(family) ? "箱" : "柜"}`;
  }
  const materialText = material === "SUS304" ? "不锈钢304材质"
    : material === "SUS316" ? "不锈钢316材质" : "碳钢";
  const ral = source.match(/RAL\s*(\d{4})/i)?.[1] || "7035";
  const texture = /[桔橘]/.test(coating) ? "橘纹" : coating.includes("平") ? "平光" : "";
  const finish = coating && coating !== "无" ? `喷塑RAL${ral}${texture}` : "";
  const body = source.match(/柜体(?:厚)?\s*[:：]?\s*(\d+(?:\.\d+)?)/)?.[1] || "1.5";
  const door = source.match(/门板(?:厚)?\s*[:：]?\s*(\d+(?:\.\d+)?)/)?.[1] || "2.0";
  const parts = [structure, materialText];
  if (finish) {
    if (["SUS304", "SUS316"].includes(material)) parts.push(`表面${finish}`);
    else parts[parts.length - 1] += finish;
  }
  parts.push(`柜体${body}`, `门板${door}`);
  const doorPhrase = source.match(/前(?:单|双)开门后(?:背板|单开门|双开门)/)?.[0];
  if (doorPhrase) parts.push(doorPhrase);
  else if (/双|DOUBLE/i.test(variant)) parts.push("前双开门后背板");
  else if (/单|SINGLE/i.test(variant)) parts.push("前单开门后背板");
  const seen = new Set();
  for (const attachment of item.attachments || []) {
    const wording = attachmentRemark(attachment);
    if (wording && !seen.has(wording)) { parts.push(wording); seen.add(wording); }
  }
  return `${parts.filter(Boolean).join("，").replace(/[，。；;\s]+$/u, "")}。`;
};

function fillSheet(sheet, method) {
  const items = payload.items || [];
  const lastColumn = method === "formula" ? "AC" : "Y";
  const columnCount = method === "formula" ? 29 : 25;
  const discountColumn = method === "formula" ? "AC" : "Y";
  const firstRow = 11;
  const dataEnd = firstRow + items.length - 1;
  const subtotalRow = firstRow + items.length;
  const endRow = Math.max(20, subtotalRow);
  // The template has seven visual item rows (11..17).  Rows beyond that are
  // copied from its last item row, so there is no page break or second header.
  sheet.getRange(`A${firstRow}:${lastColumn}${endRow}`).clear({ applyTo: "contents" });
  if (items.length > 7) {
    for (let row = 18; row <= dataEnd; row += 1) {
      sheet.getRange(`A${row}:${lastColumn}${row}`).copyFrom(
        sheet.getRange(`A17:${lastColumn}17`), "all",
      );
      sheet.getRange(`A${row}:${lastColumn}${row}`).format.rowHeight = templateRowHeights[17];
    }
  }
  if (subtotalRow !== 18) {
    sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).copyFrom(
      sheet.getRange(`A18:${lastColumn}18`), "all",
    );
    sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).format.rowHeight = templateRowHeights[18];
  }
  // Remove unused template rows below the subtotal.  Keep row 20 as the
  // unboxed validity note from the reference workbook.
  if (subtotalRow < 19) {
    sheet.getRange(`A${subtotalRow + 1}:${lastColumn}19`).clear({ applyTo: "all" });
  }
  sheet.getRange(`${discountColumn}10`).values = [["折扣"]];
  // The source template has an old order-level discount placeholder in L8/L9.
  // Discounts are now per cabinet in the new column after 运费, so remove it.
  sheet.getRange("L8:M9").clear({ applyTo: "contents" });
  sheet.getRange("D1").values = [[payload.quote_id || ""]];
  const now = new Date();
  const today = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  // The fixed template labels the date in D2 and merges E2:G2 for its value.
  // Always populate that visible value cell; use today's date as a safe fallback.
  sheet.getRange("E2").values = [[payload.quote_date || today]];
  sheet.getRange("B4").values = [[payload.company_name || ""]];
  let subtotal = 0;
  items.forEach((item, index) => {
    const row = firstRow + index;
    const quote = method === "formula" ? item.formula : item.quick;
    const discount = asNumber(method === "formula" ? item.formula_discount : item.quick_discount) || 1;
    const unitCost = asNumber(quote?.total_cost) * discount;
    const qty = asNumber(item.quantity || 1);
    subtotal += unitCost * qty;
    // final_remark is the operator-confirmed wording shown on the Remarks page.
    // Keep notes as a backward-compatible fallback for older saved drafts.
    const note = standardizedRemark(item);
    // 规格型号始终是柜体尺寸，不能再被 PDF 编号或产品规格覆盖。
    const spec = `${fmt(item.width_mm)}×${fmt(item.height_mm)}×${fmt(item.depth_mm)}`;
    const values = Array(columnCount).fill("");
    values[0] = index + 1;
    values[1] = drawingNameBeforeChinese(
      item.source_pdf_name || item.name || item.product_family || item.product_code,
    );
    values[2] = spec;
    values[3] = qty;
    values[4] = "台";
    values[5] = unitCost;
    // G/H/I deliberately remain blank: historical/amount fields are pending.
    values[9] = note;
    const attachments = item.attachments || [];
    const extras = attachmentAmounts(attachments, discount, method);
    for (const [columnIndex, amount] of Object.entries(extras)) values[Number(columnIndex) - 1] = amount;
    const attachmentFee = quote?.attachment_fee !== null
      && quote?.attachment_fee !== undefined
      && Number.isFinite(Number(quote.attachment_fee))
      ? Number(quote.attachment_fee)
      : attachmentTotalFromItems(attachments);
    if (method === "formula") {
      // Keep the five component columns reconcilable with the discounted
      // formula-method unit price.  Attachment prices use the same discount.
      values[11] = asNumber(quote?.material_cost) * discount;
      values[12] = asNumber(quote?.auxiliary_cost) * discount;
      values[13] = asNumber(quote?.labor_cost) * discount;
      values[14] = asNumber(quote?.spray_cost) * discount;
      values[15] = asNumber(quote?.management_fee) * discount;
      values[28] = discount;
    } else {
      // The quick sheet remains unchanged: “柜体” is the selected quote's
      // final price excluding attachments.
      values[11] = Math.max(0, (asNumber(quote?.total_cost) - attachmentFee) * discount);
      values[24] = discount;
    }
    sheet.getRange(`A${row}:${lastColumn}${row}`).values = [values];
    sheet.getRange(`J${row}`).format.wrapText = true;
    sheet.getRange(`J${row}`).format.verticalAlignment = "middle";
  });
  sheet.getRange(`A${subtotalRow}`).values = [["本页小计"]];
  sheet.getRange(`F${subtotalRow}`).values = [[subtotal]];
  sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).format.font = { bold: true };
  sheet.getRange(`F${firstRow}:F${subtotalRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`L${firstRow}:${col(columnCount - 1)}${dataEnd}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`${discountColumn}${firstRow}:${discountColumn}${dataEnd}`).format.numberFormat = "0.00";
}

let costDetailLastRow = 7;

function buildFormulaCostDetailSheet() {
  const sheet = workbook.worksheets.add("成本明细");
  const items = payload.items || [];
  const headers = [
    "柜号", "名称", "规格型号", "成本类别", "明细项目", "规格/说明",
    "计算公式/计价依据", "用量", "单位", "单价（元）", "单台金额（元）",
    "柜体数量", "行金额（元）", "数据来源", "备注",
  ];
  const lastColumn = col(headers.length);
  const firstDataRow = 6;
  const detailRows = [];
  const detailStyles = [];

  const addDetail = (itemIndex, item, category, detailName, spec, basis, usage, unit,
    unitPrice, unitAmount, source, note = "", kind = "detail") => {
    const cabinetQuantity = asNumber(item.quantity || 1);
    detailRows.push([
      itemIndex + 1,
      drawingNameBeforeChinese(
        item.source_pdf_name || item.name || item.product_family || item.product_code,
      ),
      `${fmt(item.width_mm)}×${fmt(item.height_mm)}×${fmt(item.depth_mm)}`,
      category,
      detailName,
      spec || "",
      basis || "",
      usage === null || usage === undefined ? "" : usage,
      unit || "",
      unitPrice === null || unitPrice === undefined ? "" : unitPrice,
      unitAmount === null || unitAmount === undefined ? "" : unitAmount,
      cabinetQuantity,
      unitAmount === null || unitAmount === undefined ? "" : asNumber(unitAmount) * cabinetQuantity,
      source || "",
      note || "",
    ]);
    detailStyles.push(kind);
  };

  items.forEach((item, itemIndex) => {
    const quote = item.formula || {};
    const materialCost = asNumber(quote.material_cost);
    const materialUnitPrice = Number(quote.material_unit_price);
    const correctedWeight = Number(quote.corrected_material_weight_kg);
    const weight = Number.isFinite(correctedWeight)
      ? correctedWeight
      : (Number.isFinite(materialUnitPrice) && materialUnitPrice > 0 ? materialCost / materialUnitPrice : null);
    addDetail(
      itemIndex, item, "材料成本", `${item.material_code || "材料"}板材`,
      item.material_code || "", Number.isFinite(weight) && Number.isFinite(materialUnitPrice)
        ? `${weight.toFixed(6)} kg × ${materialUnitPrice.toFixed(4)} 元/kg = ${materialCost.toFixed(2)} 元`
        : "修正后材料重量 × 材料单价",
      weight, "kg", Number.isFinite(materialUnitPrice) ? materialUnitPrice : null,
      materialCost, "数据库材料价格历史", "材料重量为公式法修正后重量",
    );

    const auxiliaryCost = asNumber(quote.auxiliary_cost);
    const auxiliary = item.auxiliary_detail || {};
    const auxiliaryLines = Array.isArray(auxiliary.lines) ? auxiliary.lines : [];
    let auxiliaryLineSum = 0;
    for (const line of auxiliaryLines) {
      const quantity = asNumber(line.quantity);
      const price = Number(line.unit_price);
      const amount = Number.isFinite(Number(line.line_total))
        ? Number(line.line_total)
        : (Number.isFinite(price) ? quantity * price : 0);
      auxiliaryLineSum += amount;
      addDetail(
        itemIndex, item, "辅材成本", line.item_name || line.item_code || "辅材",
        [line.spec_model, line.material_name].filter(Boolean).join(" / "),
        Number.isFinite(price) ? `${quantity} × ${price.toFixed(4)} = ${amount.toFixed(2)} 元` : "BOM 用量 × 辅材单价",
        quantity, "件", Number.isFinite(price) ? price : null, amount,
        [auxiliary.source_file, auxiliary.source_sheet || line.source_sheet].filter(Boolean).join(" / ") || "数据库辅材 BOM",
        line.source_row_no ? `源表第 ${line.source_row_no} 行` : "",
      );
    }
    if (!auxiliaryLines.length) {
      addDetail(
        itemIndex, item, "辅材成本", "辅材成本（经验值）", "无 BOM 明细",
        "数据库辅材经验值（同柜型尺寸规则）", 1, "项", auxiliaryCost, auxiliaryCost,
        "数据库辅材经验值", "该柜型按经验值计价",
      );
      auxiliaryLineSum = auxiliaryCost;
    } else if (Math.abs(auxiliaryCost - auxiliaryLineSum) > 0.01) {
      const adjustment = auxiliaryCost - auxiliaryLineSum;
      addDetail(
        itemIndex, item, "辅材成本", "BOM 汇总调整", "使 BOM 明细与公式法辅材成本一致",
        `${auxiliaryCost.toFixed(2)} - ${auxiliaryLineSum.toFixed(2)} = ${adjustment.toFixed(2)} 元`,
        1, "项", adjustment, adjustment, "数据库公式法计算结果",
        "源表 BOM 合计与当前计价结果的差额", "adjustment",
      );
    }

    const laborCost = asNumber(quote.labor_cost);
    addDetail(
      itemIndex, item, "人工成本", "人工成本（经验值）", "同柜型/同材质/最近尺寸",
      "数据库人工经验值（已含人工成本修正系数）", 1, "项", laborCost, laborCost,
      "数据库人工经验值", "非精确尺寸按同柜型最近尺寸及周长比例修正",
    );

    const attachmentCost = asNumber(quote.attachment_fee);
    const attachments = Array.isArray(item.attachments) ? item.attachments : [];
    let attachmentLineSum = 0;
    for (const attachment of attachments) {
      const quantity = asNumber(attachment.quantity || 1);
      const price = attachmentUnitPrice(attachment);
      const amount = attachmentLineAmount(attachment);
      attachmentLineSum += amount;
      addDetail(
        itemIndex, item, "附件成本", attachment.item_name || attachment.model_code || "附件",
        [attachment.model_code, attachment.variant, attachment.notes].filter(Boolean).join(" / "),
        `${quantity} × ${price.toFixed(2)} = ${amount.toFixed(2)} 元`, quantity, "件", price, amount,
        attachment.price_source || "数据库附件价格表", "用户实际选择附件",
      );
    }
    if (!attachments.length && attachmentCost > 0) {
      addDetail(
        itemIndex, item, "附件成本", "附件费用汇总", "缺少逐项选择记录",
        "数据库已选附件费用汇总", 1, "项", attachmentCost, attachmentCost,
        "数据库附件选择记录", "建议补充附件逐项明细",
      );
      attachmentLineSum = attachmentCost;
    } else if (Math.abs(attachmentCost - attachmentLineSum) > 0.01) {
      const adjustment = attachmentCost - attachmentLineSum;
      addDetail(
        itemIndex, item, "附件成本", "附件汇总调整", "使附件明细与公式法附件费用一致",
        `${attachmentCost.toFixed(2)} - ${attachmentLineSum.toFixed(2)} = ${adjustment.toFixed(2)} 元`,
        1, "项", adjustment, adjustment, "数据库公式法计算结果", "附件逐项金额与计价结果的差额", "adjustment",
      );
    }

    const sprayCost = asNumber(quote.spray_cost);
    const productArea = Number(quote.product_area_m2);
    const sprayUnitPrice = Number(quote.spray_unit_price);
    if (Number.isFinite(productArea) && Number.isFinite(sprayUnitPrice)) {
      addDetail(
        itemIndex, item, "喷塑费用", `${item.coating_type || "喷塑"}`, "产品喷涂面积",
        `${productArea.toFixed(6)} m² × ${sprayUnitPrice.toFixed(4)} 元/m² = ${sprayCost.toFixed(2)} 元`,
        productArea, "m²", sprayUnitPrice, sprayCost, "数据库喷塑单价历史", "产品面积由公式模板计算",
      );
    } else {
      addDetail(
        itemIndex, item, "喷塑费用", `${item.coating_type || "喷塑"}（经验值）`, "直接喷塑价格",
        "数据库喷塑经验值（无面积公式）", 1, "项", sprayCost, sprayCost,
        "数据库喷塑经验值", "经验值柜型按同柜型最近尺寸及周长比例修正",
      );
    }

    const managementCost = asNumber(quote.management_fee);
    addDetail(
      itemIndex, item, "管理费用", "管理费用", "人工成本的 13%",
      `${laborCost.toFixed(2)} × 0.13 = ${managementCost.toFixed(2)} 元`,
      laborCost, "元", 0.13, managementCost, "系统统一公式", "管理费用＝人工成本×0.13",
    );

    const componentTotal = materialCost + auxiliaryCost + laborCost + attachmentCost + sprayCost + managementCost;
    const formulaCost = asNumber(quote.total_cost);
    if (Math.abs(formulaCost - componentTotal) > 0.01) {
      const adjustment = formulaCost - componentTotal;
      addDetail(
        itemIndex, item, "汇总调整", "成本汇总差额", "使分项合计与数据库公式法总成本一致",
        `${formulaCost.toFixed(2)} - ${componentTotal.toFixed(2)} = ${adjustment.toFixed(2)} 元`,
        1, "项", adjustment, adjustment, "数据库公式法计算结果", "需复核产生差额的历史规则", "adjustment",
      );
    }
    const discount = asNumber(item.formula_discount) || 1;
    addDetail(
      itemIndex, item, "柜型小计", "公式法成本", `折扣 ${discount.toFixed(2)}`,
      `${formulaCost.toFixed(2)} × ${discount.toFixed(2)} = ${(formulaCost * discount).toFixed(2)} 元/台`,
      1, "台", formulaCost, formulaCost * discount, "公式法报价结果",
      `折后单价；共 ${asNumber(item.quantity || 1)} 台`, "subtotal",
    );
  });

  const subtotalRow = firstDataRow + detailRows.length;
  costDetailLastRow = subtotalRow;

  sheet.mergeCells(`A1:${lastColumn}1`);
  sheet.getRange("A1").values = [["公式法报价成本明细"]];
  sheet.getRange("A2").values = [["报价编号"]];
  sheet.getRange("B2").values = [[payload.quote_id || ""]];
  sheet.getRange("D2").values = [["报价日期"]];
  sheet.getRange("E2").values = [[payload.quote_date || ""]];
  sheet.getRange("G2").values = [["下单公司"]];
  sheet.mergeCells(`H2:${lastColumn}2`);
  sheet.getRange("H2").values = [[payload.company_name || ""]];
  sheet.mergeCells(`A3:${lastColumn}3`);
  sheet.getRange("A3").values = [[
    "说明：材料和喷塑展示完整计算公式；辅材按 BOM 逐行展开；附件按实际选择逐行展开；经验值与调整项均明确标注数据来源。",
  ]];
  sheet.getRange(`A5:${lastColumn}5`).values = [headers];
  if (detailRows.length) {
    sheet.getRange(`A${firstDataRow}:${lastColumn}${subtotalRow - 1}`).values = detailRows;
  }
  sheet.getRange(`A${subtotalRow}:J${subtotalRow}`).merge();
  sheet.getRange(`A${subtotalRow}`).values = [["合计"]];
  const formulaOrderTotal = items.reduce((sum, item) => sum
    + asNumber(item.formula?.total_cost) * (asNumber(item.formula_discount) || 1) * asNumber(item.quantity || 1), 0);
  sheet.getRange(`K${subtotalRow}:O${subtotalRow}`).values = [["", "", formulaOrderTotal, "", "折后订单总成本"]];

  sheet.getRange(`A1:${lastColumn}1`).format.fill = "#173F67";
  sheet.getRange(`A1:${lastColumn}1`).format.font = { bold: true, color: "#FFFFFF", size: 16 };
  sheet.getRange(`A1:${lastColumn}1`).format.horizontalAlignment = "center";
  sheet.getRange(`A1:${lastColumn}1`).format.verticalAlignment = "middle";
  sheet.getRange(`A1:${lastColumn}1`).format.rowHeight = 32;

  sheet.getRange(`A2:${lastColumn}2`).format.fill = "#EAF2F8";
  sheet.getRange(`A2:${lastColumn}2`).format.font = { bold: true, color: "#173F67" };
  sheet.getRange(`A3:${lastColumn}3`).format.fill = "#FFF7E6";
  sheet.getRange(`A3:${lastColumn}3`).format.font = { color: "#8A5A00" };
  sheet.getRange(`A3:${lastColumn}3`).format.wrapText = true;
  sheet.getRange(`A3:${lastColumn}3`).format.rowHeight = 34;

  sheet.getRange(`A5:${lastColumn}5`).format.fill = "#2F7DC5";
  sheet.getRange(`A5:${lastColumn}5`).format.font = { bold: true, color: "#FFFFFF" };
  sheet.getRange(`A5:${lastColumn}5`).format.horizontalAlignment = "center";
  sheet.getRange(`A5:${lastColumn}5`).format.verticalAlignment = "middle";
  sheet.getRange(`A5:${lastColumn}5`).format.wrapText = true;
  sheet.getRange(`A5:${lastColumn}5`).format.rowHeight = 30;

  const tableEndRow = Math.max(subtotalRow, firstDataRow);
  sheet.getRange(`A5:${lastColumn}${tableEndRow}`).format.borders = {
    preset: "all", style: "thin", color: "#B8C7D9",
  };
  if (detailRows.length) {
    sheet.getRange(`A${firstDataRow}:${lastColumn}${subtotalRow - 1}`).format.rowHeight = 24;
    sheet.getRange(`A${firstDataRow}:O${subtotalRow - 1}`).format.verticalAlignment = "middle";
    sheet.getRange(`B${firstDataRow}:G${subtotalRow - 1}`).format.wrapText = true;
    sheet.getRange(`N${firstDataRow}:O${subtotalRow - 1}`).format.wrapText = true;
    sheet.getRange(`H${firstDataRow}:H${subtotalRow - 1}`).format.numberFormat = "#,##0.000000";
    sheet.getRange(`J${firstDataRow}:M${subtotalRow - 1}`).format.numberFormat = "#,##0.00";
    detailStyles.forEach((kind, index) => {
      const row = firstDataRow + index;
      if (kind === "subtotal") {
        sheet.getRange(`A${row}:O${row}`).format.fill = "#EAF2F8";
        sheet.getRange(`A${row}:O${row}`).format.font = { bold: true, color: "#173F67" };
      } else if (kind === "adjustment") {
        sheet.getRange(`D${row}:O${row}`).format.fill = "#FFF7E6";
        sheet.getRange(`D${row}:O${row}`).format.font = { color: "#8A5A00" };
      }
    });
  }
  sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).format.fill = "#DDEBF7";
  sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).format.font = { bold: true, color: "#173F67" };
  sheet.getRange(`K${subtotalRow}:M${subtotalRow}`).format.numberFormat = "#,##0.00";

  const widths = {
    A: 7, B: 22, C: 18, D: 13, E: 22, F: 22, G: 46,
    H: 12, I: 9, J: 13, K: 15, L: 11, M: 15, N: 25, O: 28,
  };
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}1:${column}${tableEndRow}`).format.columnWidth = width;
  }
  return sheet;
}

fillSheet(formulaSheet, "formula");
fillSheet(quickSheet, "quick");
buildFormulaCostDetailSheet();
for (const sheetName of ["公式法报价单", "快速报价单", "成本明细"]) {
  const auditLastColumn = sheetName === "公式法报价单" ? "AC"
    : sheetName === "快速报价单" ? "Y" : "O";
  const audit = await workbook.inspect({
    kind: "table",
    sheetId: sheetName,
    range: sheetName === "成本明细" ? `A1:${auditLastColumn}${costDetailLastRow}`
      : `A10:${auditLastColumn}25`,
    maxChars: 16000,
  });
  if (!audit || !audit.ndjson) throw new Error(`workbook verification failed: ${sheetName}`);
}
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formal quotation formula error scan",
});
if (formulaErrors?.ndjson && /\"matchCount\"\s*:\s*[1-9]/.test(formulaErrors.ndjson)) {
  throw new Error("formal quotation contains formula errors");
}
if (process.env.QUOTE_EXPORT_QA_DIR) {
  await fs.mkdir(process.env.QUOTE_EXPORT_QA_DIR, { recursive: true });
  const remarkAudit = {};
  for (const sheetName of ["公式法报价单", "快速报价单", "成本明细"]) {
    const previewLastColumn = sheetName === "公式法报价单" ? "AC"
      : sheetName === "快速报价单" ? "Y" : "O";
    const remarks = await workbook.inspect({
      kind: "table",
      sheetId: sheetName,
      range: sheetName === "成本明细"
        ? `A1:O${costDetailLastRow}`
        : `B10:J${Math.max(11, 10 + (payload.items || []).length)}`,
      include: "values,formulas",
      tableMaxRows: sheetName === "成本明细" ? costDetailLastRow : Math.max(2, (payload.items || []).length + 1),
      tableMaxCols: sheetName === "成本明细" ? 15 : 9,
      maxChars: 12000,
    });
    remarkAudit[sheetName] = remarks?.ndjson || "";
    const preview = await workbook.render({
      sheetName,
      range: `A1:${previewLastColumn}20`,
      scale: 1,
      format: "png",
    });
    const fileName = sheetName === "公式法报价单" ? "formula.png"
      : sheetName === "快速报价单" ? "quick.png" : "cost-detail.png";
    await fs.writeFile(
      path.join(process.env.QUOTE_EXPORT_QA_DIR, fileName),
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
  await fs.writeFile(
    path.join(process.env.QUOTE_EXPORT_QA_DIR, "remarks-audit.json"),
    JSON.stringify(remarkAudit, null, 2),
    "utf8",
  );
}
// Generate beside the destination first and publish only after the workbook
// is complete. A crash can no longer leave a zero-byte or half-written final
// quotation in the user's folder.
const resolvedOutputPath = path.resolve(outputPath);
await fs.mkdir(path.dirname(resolvedOutputPath), { recursive: true });
const temporaryOutputPath = `${resolvedOutputPath}.tmp-${process.pid}-${Date.now()}.xlsx`;
try {
  const out = await SpreadsheetFile.exportXlsx(workbook);
  await out.save(temporaryOutputPath);
  const stat = await fs.stat(temporaryOutputPath);
  if (!stat.isFile() || stat.size === 0) throw new Error("导出组件生成了空文件");
  await fs.copyFile(temporaryOutputPath, resolvedOutputPath);
  const finalStat = await fs.stat(resolvedOutputPath);
  if (!finalStat.isFile() || finalStat.size !== stat.size) {
    throw new Error("正式报价单落盘校验失败");
  }
} finally {
  await fs.rm(temporaryOutputPath, { force: true });
  await fs.rm(`${temporaryOutputPath}.inspect.ndjson`, { force: true });
  // The artifact verifier may write a diagnostic sidecar next to the workbook.
  await fs.rm(`${resolvedOutputPath}.inspect.ndjson`, { force: true });
}
console.log(`exported ${resolvedOutputPath}`);
