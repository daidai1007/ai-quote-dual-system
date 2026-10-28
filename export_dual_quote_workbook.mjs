/*
 * Formal dual quotation workbook exporter.
 *
 * Input is a confirmed multi-cabinet JSON snapshot.  The public quotation
 * layout is generated from a sanitized, code-owned template so source and
 * packaged deployments do not depend on a private workbook or Codex runtime.
 * Cabinet components remain database-owned. Management is rederived using
 * the shared six-component rule and the already-confirmed popup costs.
 */
import ExcelJS from "@excel.js/exceljs";
import fs from "node:fs/promises";
import {documentWithOrderNature,orderNatureLabel} from './quote_order_nature.mjs';
import path from "node:path";
import {addAttachmentSnapshotSheet} from "./attachment_snapshot_export.mjs";
import {withAttachmentCostAllocation} from './attachment_cost_allocation.mjs';
import {
  attachRangeApi,
  attachWorkbookRangeApi,
  rangePlainValues,
  scanWorkbookFormulaErrors,
} from "./exceljs_range_adapter.mjs";
import {
  isDrawingSourcedQuoteItem,
  validateConfirmedQuoteSnapshot,
} from "./quote_export_contract.mjs";
import {
  attachmentExcludedFromDiscount,
  attachmentUsesCabinetQuantity,
  effectiveAttachmentLineAmount,
  effectiveFormulaAttachmentLineAmount,
  formulaAttachmentLineAmount,
  effectiveAttachmentQuantity,
  formulaAttachmentExcluded,
  quickDiscountBreakdown,
  quickDiscountCategory,
  quickOrderLineBreakdown,
  money, moneySum, moneyProduct, PRICING_BASIS, validateQuoteDisplay, applyManagementFee, missingManagementCosts, MANAGEMENT_FEE_RATE,
} from "./quick_discount_rules.mjs";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: export_dual_quote_workbook.mjs input.json output.xlsx");
const payload = documentWithOrderNature(JSON.parse(await fs.readFile(inputPath, "utf8")));
if (!Array.isArray(payload.items) || payload.items.length === 0) {
  throw new Error("报价清单为空，无法生成正式报价单");
}
validateConfirmedQuoteSnapshot(payload);
// Management is always derived from current components, including popup costs.
// Neither a saved fee, a saved total nor a historical rate may price an export.
for (const [index,item] of payload.items.entries()) {
  const rows=item.quote_display?.attachment_source==='popup_v1'
    ? item.quote_display.attachments : item.attachments||[];
  item.attachments=rows;
  const formula={...(item.formula||{}),attachment_fee:moneySum(rows.map(formulaAttachmentLineAmount))};
  const missing=missingManagementCosts(formula);
  if(missing.length) throw new Error(`第${index+1}行柜体成本分项缺失（${missing.join('、')}），请重新计算整柜`);
  const normalized=applyManagementFee(formula,item.freight_fee??item.freight??0);
  if(item.preserve_legacy_cost_classes){delete normalized.cost_allocation;item.formula=normalized;}
  else item.formula=withAttachmentCostAllocation(normalized,rows,
    {strict:!!item.formula?.cost_allocation?.complete||rows.some(row=>row.cost_method==='FORMULA')});
}

const sellerInformation = {
  name: "浙江京能电力设备有限公司",
  address: "杭州临安横畈工业功能区桑园路18号",
  telephone: "0571-88520091",
  fax: "0571-88520077",
  email: "",
};
// Keep customer-facing sheets on the established desktop-client template.
const LEGACY_FORMULA_HEADERS = [
  "序号", "名称", "规格型号(W*D*H)", "数量", "单位", "单价", "总价", "备注",
];
const LEGACY_QUICK_HEADERS = [
  "序号", "名称", "规格型号(W*D*H)", "数量", "单位", "折后单价", "折后总价", "备注",
];

// Cross-sheet copyFrom() also does not reproduce the source worksheet's
// merged cells, column widths or row heights. Apply the fixed template
// geometry explicitly so both quotation sheets have the same layout in
// Excel/WPS.
const templateColumnWidths = {
  A: 5,
  B: 18,
  C: 24,
  D: 7,
  E: 7,
  F: 11,
  G: 12,
  H: 58,
  I: 3,
  J: 3,
  K: 3,
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
const QUICK_ATTACHMENT_CATEGORY_ORDER = [
  "底座", "侧板", "安装板", "内门", "玻璃门", "通风顶罩", "防雨顶", "分段板", "JK安装板",
];
const quoteDisplay = (item = {}) => (
  item.quote_display && typeof item.quote_display === "object" && !Array.isArray(item.quote_display)
    ? item.quote_display : null
);
const quickExportAttachments = (item = {}) => {
  const display = quoteDisplay(item);
  return Array.isArray(display?.attachments) ? display.attachments : (item.attachments || []);
};
const quickExportQuote = (item = {}) => {
  const display = quoteDisplay(item);
  const quote = { ...(item.quick || {}) };
  for (const [displayKey, quoteKey] of [
    ["quick_total_cost", "total_cost"],
    ["quick_attachment_fee", "attachment_fee"],
    ["quick_base_price", "base_price"],
  ]) {
    const value = display?.[displayKey];
    if (value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))) {
      quote[quoteKey] = Number(value);
    }
  }
  return quote;
};
const quickAttachmentName = (item = {}) => String(item.item_name || item.model_code || "未命名附件").trim();
const earlyAttachmentLineAmount = (item = {}) => {
  const sign = Number(item.attachment_price_sign) === -1 ? -1 : 1;
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      return Math.abs(Number(item[key])) * sign;
    }
  }
  let unitPrice = 0;
  for (const key of ["unit_price_override", "matched_price", "unit_price", "price"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      unitPrice = Math.abs(Number(item[key]));
      break;
    }
  }
  const quantity = Number.isFinite(Number(item.quantity)) ? Number(item.quantity) : 1;
  return unitPrice * quantity * sign;
};
const quickItemsByName = new Map();
for (const item of payload.items.flatMap(quickExportAttachments)) {
  const name = quickAttachmentName(item);
  if (!name) continue;
  if (!quickItemsByName.has(name)) quickItemsByName.set(name, []);
  quickItemsByName.get(name).push(item);
}
const quickAttachmentNames = [...new Set(
  payload.items.flatMap((item) => quickExportAttachments(item).map(quickAttachmentName)).filter(Boolean),
)].sort((left, right) => {
  const rankFor = (name) => Math.min(999, ...(quickItemsByName.get(name) || [])
    .map(quickDiscountCategory)
    .filter(Boolean)
    .map((category) => QUICK_ATTACHMENT_CATEGORY_ORDER.indexOf(category)));
  const leftRank = rankFor(left);
  const rightRank = rankFor(right);
  return leftRank - rightRank || left.localeCompare(right, "zh-CN", { numeric: true, sensitivity: "base" });
});
// The formula quotation must expose the same attachment-name detail as the
// quick quotation.  Use the union so a formula-cost row that is absent from a
// legacy quick snapshot is still visible instead of being silently dropped.
const formulaAttachmentNames = [...new Set(
  payload.items.flatMap((item) => [
    ...quickExportAttachments(item),
    ...(Array.isArray(item.attachments) ? item.attachments : []),
  ].map(quickAttachmentName)).filter(Boolean),
)].sort((left, right) => {
  const rankFor = (name) => Math.min(999, ...(quickItemsByName.get(name) || [])
    .map(quickDiscountCategory)
    .filter(Boolean)
    .map((category) => QUICK_ATTACHMENT_CATEGORY_ORDER.indexOf(category)));
  const leftRank = rankFor(left);
  const rightRank = rankFor(right);
  return leftRank - rightRank || left.localeCompare(right, "zh-CN", { numeric: true, sensitivity: "base" });
});
// Every attachment fee is represented by a current popup row, so no
// synthetic "other attachment/delta" column is needed.
const hasQuickOtherColumn = false;
const unitSetWorkbook = payload.items.some(item => item.pricing_basis === PRICING_BASIS);
const hasMaterialDifference = payload.items.some(item => Number(item.quote_display?.material_difference || 0) !== 0);
const quickCostHeaders = [
  "原价单价", unitSetWorkbook ? "原价总价" : "折后单价", "柜体", ...quickAttachmentNames,
  ...(hasQuickOtherColumn ? ["其他附件/差额"] : []), ...(hasMaterialDifference ? ["材料差价"] : []), "运费", "折扣",
];
const quickNameColumnByName = new Map(
  quickAttachmentNames.map((name, index) => [name, 13 + index]),
);
const quickOtherColumnIndex = hasQuickOtherColumn ? 13 + quickAttachmentNames.length : null;
const quickMaterialColumnIndex = hasMaterialDifference ? 13 + quickAttachmentNames.length : null;
const quickFreightColumnIndex = 13 + quickAttachmentNames.length + (hasQuickOtherColumn ? 1 : 0) + (hasMaterialDifference ? 1 : 0);
const quickDiscountColumnIndex = quickFreightColumnIndex + 1;
const formulaAttachmentStartColumnIndex = 17; // Q, after L:P formula components
const formulaNameColumnByName = new Map(
  formulaAttachmentNames.map((name, index) => [name, formulaAttachmentStartColumnIndex + index]),
);
const formulaFreightColumnIndex = formulaAttachmentStartColumnIndex + formulaAttachmentNames.length;
const formulaDiscountColumnIndex = formulaFreightColumnIndex + 1;
const formulaCostHeaders = [
  ...formulaAttachmentNames, "运费", "折扣",
];
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
  "B4:D4", "F4:H4",
  "B5:D5", "F5:H5",
  "B6:D6", "F6:H6",
  "B7:D7", "F7:H7",
  "B8:D8", "F8:H8",
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

function buildQuotationTemplate(targetWorkbook) {
  const sheet = attachRangeApi(targetWorkbook.addWorksheet("报价模板"));
  sheet.views = [{ showGridLines: false }];
  applyTemplateGeometry(sheet, true);

  sheet.getRange("A1").values = [["报价单"]];
  sheet.getRange("D1").values = [["编号"]];
  sheet.getRange("D2").values = [["日期"]];
  sheet.getRange("A4:A8").values = [["买方"], ["地址"], ["电话"], ["传真"], ["邮箱"]];
  sheet.getRange("E4:E8").values = [["卖方"], ["地址"], ["电话"], ["传真"], ["邮箱"]];
  sheet.getRange("F4:F8").values = [[
    sellerInformation.name,
  ], [
    sellerInformation.address,
  ], [
    sellerInformation.telephone,
  ], [
    sellerInformation.fax,
  ], [
    sellerInformation.email,
  ]];
  sheet.getRange("A10:H10").values = [LEGACY_FORMULA_HEADERS];
  sheet.getRange("L10:Y10").values = [[
    "柜体", "底座", "侧板", "三排纵梁", "安装板", "灯/开关", "文件夹",
    "风机滤网", "门限位器", "接地线", "双开门", "安装板单发", "运费", "折扣",
  ]];

  sheet.getRange("A1:Y20").format.font = {
    name: "Microsoft YaHei",
    size: 10,
    color: "#1F2937",
  };
  sheet.getRange("A1:C2").format.font = {
    name: "Microsoft YaHei",
    size: 22,
    bold: true,
    color: "#111827",
  };
  sheet.getRange("A1:C2").format.horizontalAlignment = "center";
  sheet.getRange("A1:C2").format.verticalAlignment = "middle";
  sheet.getRange("A1:C2").format.borders = {
    preset: "all", style: "medium", color: "#1F2937",
  };
  sheet.getRange("D1:G2").format.horizontalAlignment = "center";
  sheet.getRange("D1:G2").format.verticalAlignment = "middle";
  sheet.getRange("D1:G2").format.borders = {
    preset: "all", style: "medium", color: "#1F2937",
  };
  sheet.getRange("D1:D2").format.font = { bold: true, color: "#374151" };

  for (const row of [4, 5, 6, 7, 8]) {
    for (const range of [`A${row}:D${row}`, `E${row}:H${row}`]) {
      sheet.getRange(range).format.borders = {
        bottom: { style: "thin", color: "#374151" },
      };
    }
  }
  sheet.getRange("A4:A8").format.font = { bold: true, color: "#374151" };
  sheet.getRange("E4:E8").format.font = { bold: true, color: "#374151" };
  sheet.getRange("B4:D8").format.horizontalAlignment = "center";
  sheet.getRange("F4:H8").format.horizontalAlignment = "center";

  sheet.getRange("A10:H10").format.fill = "#E9EEF5";
  sheet.getRange("A10:H10").format.font = { bold: true, color: "#1F3A5F" };
  sheet.getRange("A10:H10").format.horizontalAlignment = "center";
  sheet.getRange("A10:H10").format.verticalAlignment = "middle";
  sheet.getRange("A10:H10").format.wrapText = true;
  sheet.getRange("A10:H10").format.borders = {
    preset: "all", style: "thin", color: "#4B5563",
  };

  sheet.getRange("A11:H17").format.verticalAlignment = "middle";
  sheet.getRange("A11:H17").format.wrapText = true;
  sheet.getRange("A11:H17").format.borders = {
    preset: "all", style: "thin", color: "#6B7280",
  };
  sheet.getRange("A11:G17").format.horizontalAlignment = "center";
  sheet.getRange("H11:H17").format.horizontalAlignment = "left";
  sheet.getRange("A18:H18").format.fill = "#F3F6FA";
  sheet.getRange("A18:H18").format.font = { bold: true, color: "#1F3A5F" };
  sheet.getRange("A18:H18").format.verticalAlignment = "middle";
  sheet.getRange("A18:H18").format.borders = {
    preset: "all", style: "thin", color: "#4B5563",
  };
  sheet.getRange("A18:G18").format.horizontalAlignment = "center";
  sheet.getRange("F11:G18").format.numberFormat = "#,##0.00";

  sheet.getRange("L10:Y10").format.fill = "#EEF3F8";
  sheet.getRange("L10:Y10").format.font = { bold: true, color: "#40566F" };
  sheet.getRange("L10:Y10").format.horizontalAlignment = "center";
  sheet.getRange("L10:Y10").format.verticalAlignment = "middle";
  sheet.getRange("L10:Y10").format.wrapText = true;
  sheet.getRange("L10:Y10").format.borders = {
    preset: "all", style: "thin", color: "#CBD5E1",
  };
  sheet.getRange("L11:Y18").format.horizontalAlignment = "center";
  sheet.getRange("L11:Y18").format.verticalAlignment = "middle";
  sheet.getRange("L11:Y18").format.numberFormat = "#,##0.00";
  return sheet;
}

const col = (n) => {
  let text = "";
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) text = String.fromCharCode(65 + (x - 1) % 26) + text;
  return text;
};

const quickLastColumn = col(quickDiscountColumnIndex);
const quickSetupEndColumn = col(Math.max(25, quickDiscountColumnIndex));

const workbook = new ExcelJS.Workbook();
const formulaSheet = buildQuotationTemplate(workbook);
formulaSheet.name = "公式法报价单";
const quickSheet = attachRangeApi(workbook.addWorksheet("快速报价单"));
quickSheet.views = [{ showGridLines: false }];
quickSheet.getRange("A1:Y20").copyFrom(formulaSheet.getRange("A1:Y20"), "all");
applyTemplateGeometry(quickSheet, true);

// Expand only the quick-quote audit area. J and K show formula-driven original
// and discounted prices, while L onward retains the auditable source amounts;
// the selected factor remains visible in the final dynamic column.
for (let targetIndex = 26; targetIndex <= quickDiscountColumnIndex; targetIndex += 1) {
  const targetLetter = col(targetIndex);
  quickSheet.getRange(`${targetLetter}1:${targetLetter}28`).copyFrom(
    quickSheet.getRange("Y1:Y28"),
    "all",
  );
  quickSheet.getRange(`${targetLetter}1:${targetLetter}28`).format.columnWidth = 10.5;
}
quickSheet.getRange(`J1:${quickLastColumn}28`).format.font = {
  name: "Microsoft YaHei", size: 10, color: "#1F2937",
};
quickSheet.getRange(`J10:${quickSetupEndColumn}18`).clear({ applyTo: "contents" });
if (quickDiscountColumnIndex < 25) {
  quickSheet.getRange(`${col(quickDiscountColumnIndex + 1)}10:Y18`).clear({ applyTo: "all" });
}
quickSheet.getRange(`J10:${quickLastColumn}10`).values = [quickCostHeaders];
quickSheet.getRange("F10:G10").values = [["折后单价", "折后总价"]];
quickSheet.getRange(`J10:${quickLastColumn}10`).format.fill = "#EEF3F8";
quickSheet.getRange(`J10:${quickLastColumn}10`).format.font = { bold: true, color: "#40566F" };
quickSheet.getRange(`J10:${quickLastColumn}10`).format.horizontalAlignment = "center";
quickSheet.getRange(`J10:${quickLastColumn}10`).format.verticalAlignment = "middle";
quickSheet.getRange(`J10:${quickLastColumn}10`).format.wrapText = true;
quickSheet.getRange(`J10:${quickLastColumn}10`).format.borders = {
  preset: "all", style: "thin", color: "#CBD5E1",
};
quickSheet.getRange(`J11:${quickLastColumn}18`).format.horizontalAlignment = "center";
quickSheet.getRange(`J11:${quickLastColumn}18`).format.verticalAlignment = "middle";
quickSheet.getRange(`J11:${quickLastColumn}18`).format.borders = {
  preset: "all", style: "thin", color: "#CBD5E1",
};
quickSheet.getRange("J1:J28").format.columnWidth = 13;
quickSheet.getRange("K1:K28").format.columnWidth = 13;
quickSheet.getRange("L1:L28").format.columnWidth = 12;
for (let index = 13; index < 13 + quickAttachmentNames.length; index += 1) {
  quickSheet.getRange(`${col(index)}1:${col(index)}28`).format.columnWidth = 14;
}
if (quickOtherColumnIndex) {
  quickSheet.getRange(`${col(quickOtherColumnIndex)}1:${col(quickOtherColumnIndex)}28`).format.columnWidth = 13;
}
quickSheet.getRange(`${col(quickFreightColumnIndex)}1:${col(quickFreightColumnIndex)}28`).format.columnWidth = 11;
quickSheet.getRange(`${col(quickDiscountColumnIndex)}1:${col(quickDiscountColumnIndex)}28`).format.columnWidth = 9;

// The formula sheet exposes its five database cost components before the
// attachment-price columns.  The quick sheet intentionally keeps the original
// fixed template unchanged.  In the formula sheet, replace the old L “柜体”
// column with the five component columns L:P, then move the original attachment
// columns M:Y four places to the right (Q:AC).  Same-sheet copyFrom preserves
// values and formatting.  The range adapter snapshots each source column so
// overlapping moves cannot overwrite columns that are still waiting to move.
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
// Replace the old fixed attachment-category block with the same dynamic
// attachment-name columns used by the quick quotation.  Extend the copied
// template style when a quote contains more names than the legacy Q:AC area.
const formulaLastColumn = col(formulaDiscountColumnIndex);
const formulaLayoutEndColumn = col(Math.max(29, formulaDiscountColumnIndex));
for (let targetIndex = formulaAttachmentStartColumnIndex; targetIndex <= formulaDiscountColumnIndex; targetIndex += 1) {
  const targetLetter = col(targetIndex);
  if (targetIndex > 29) {
    formulaSheet.getRange(`${targetLetter}1:${targetLetter}28`).copyFrom(
      formulaSheet.getRange("AC1:AC28"),
      "all",
    );
  }
  formulaSheet.getRange(`${targetLetter}1:${targetLetter}28`).format.columnWidth = 14;
}
formulaSheet.getRange(`Q10:${formulaLayoutEndColumn}18`).clear({ applyTo: "contents" });
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).values = [formulaCostHeaders];
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.fill = "#EEF3F8";
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.font = { bold: true, color: "#40566F" };
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.horizontalAlignment = "center";
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.verticalAlignment = "middle";
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.wrapText = true;
formulaSheet.getRange(`Q10:${formulaLastColumn}10`).format.borders = {
  preset: "all", style: "thin", color: "#CBD5E1",
};
formulaSheet.getRange(`Q11:${formulaLastColumn}18`).format.horizontalAlignment = "center";
formulaSheet.getRange(`Q11:${formulaLastColumn}18`).format.verticalAlignment = "middle";
formulaSheet.getRange(`Q11:${formulaLastColumn}18`).format.numberFormat = "#,##0.00";

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

const hasFiniteNumber = (value) => value !== null && value !== undefined && value !== ""
  && Number.isFinite(Number(value));
const asNumber = (value) => hasFiniteNumber(value) ? Number(value) : 0;
const optionalNumber = (value) => hasFiniteNumber(value) ? Number(value) : null;
const gangedCabinetCount = (item = {}) => {
  const stored = Number(item.ganged_cabinet_count);
  if (Number.isInteger(stored) && stored > 1) return stored;
  if (Array.isArray(item.ganged_cabinets) && item.ganged_cabinets.length > 1) {
    return item.ganged_cabinets.length;
  }
  return 1;
};
const fmt = (value) => String(asNumber(value)).replace(/\.0+$/, "");
const quoteSpecification = (item = {}) => {
  const explicit = String(item.specification || "").trim();
  if (explicit) return explicit;
  // Engineering/cost calculations retain W/H/D internally.  The approved
  // customer-facing quotation column is W*D*H.
  return `${fmt(item.width_mm)}*${fmt(item.depth_mm)}*${fmt(item.height_mm)}`;
};
const drawingNameBeforeChinese = (value) => {
  const stem = path.basename(String(value || "").trim()).replace(/\.(?:pdf|dwg|dxf|jpe?g|png|bmp|tiff?)$/i, "");
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
const attachmentFormulaCostBasis = (item = {}) => {
  const components = [
    ["材料成本", item.material_cost],
    ["喷塑成本", item.spray_cost],
    ["辅材", item.auxiliary_cost],
    ["人工", item.labor_cost],
  ];
  if (!components.some(([, value]) => hasFiniteNumber(value))) return "";
  const parts = components.map(([label, value]) => `${label} ${asNumber(value).toFixed(2)}`);
  const total = components.reduce((sum, [, value]) => sum + asNumber(value), 0);
  return `单位成本＝${parts.join(" + ")} = ${total.toFixed(2)} 元`;
};
const attachmentLineAmount = (item = {}) => {
  if(item.catalog_version && item.quick_amount != null) return Number(item.quick_amount);
  const sign = Number(item.attachment_price_sign) === -1 ? -1 : 1;
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      return Math.abs(Number(item[key])) * sign;
    }
  }
  return Math.abs(attachmentUnitPrice(item)) * (asNumber(item.quantity) || 1) * sign;
};
const attachmentAmounts = (
  attachments = [], discount = 1, method = "quick", cabinetQuantity = 1,
  gangedCount = 1,
) => {
  const out = {};
  for (const item of attachments) {
    if (method === "formula" && formulaAttachmentExcluded(item)) continue;
    let index = method === "formula"
      ? formulaNameColumnByName.get(quickAttachmentName(item))
      : attachmentColumn(item.item_name || item.model_code);
    const factor = method === "formula" && attachmentExcludedFromDiscount(item)
      ? 1 : discount;
    if (index) out[index] = (out[index] || 0)
      + (method === 'formula' ? effectiveFormulaAttachmentLineAmount(item, cabinetQuantity, gangedCount)
        : effectiveAttachmentLineAmount(item, cabinetQuantity, gangedCount)) * factor;
  }
  return out;
};
const quickAttachmentAmounts = (
  attachments = [], cabinetQuantity = 1, gangedCount = 1, preserveSnapshotAmounts = false,
) => {
  const out = {};
  for (const item of attachments) {
    const index = quickNameColumnByName.get(quickAttachmentName(item));
    if (!index) continue;
    out[index] = (out[index] || 0)
      + (preserveSnapshotAmounts
        ? effectiveAttachmentLineAmount(item, 1, 1)
        : effectiveAttachmentLineAmount(item, cabinetQuantity, gangedCount));
  }
  return out;
};
const attachmentTotalFromItems = (attachments = []) =>
  attachments.reduce((sum, item) => sum + attachmentLineAmount(item), 0);

const effectiveAttachmentTotalFromItems = (
  attachments = [], cabinetQuantity = 1, gangedCount = 1,
) =>
  attachments.reduce(
    (sum, item) => sum
      + effectiveAttachmentLineAmount(item, cabinetQuantity, gangedCount),
    0,
  );

const formulaOrderLineBreakdown = (item = {}) => {
  const quote = item.formula || {};
  const attachments = item.attachments || [];
  const cabinetQuantity = asNumber(item.quantity || 1);
  const gangedCount = gangedCabinetCount(item);
  const discount = asNumber(item.formula_discount) || 1;
  const freightFee = Math.max(0, asNumber(item.freight_fee ?? item.freight));
  const freightTotal = freightFee * cabinetQuantity;
  // Formula attachments and management have been normalized to current rules.
  const listedAttachmentTotal = attachments.reduce(
    (sum, row) => sum + (!formulaAttachmentExcluded(row)
      ? formulaAttachmentLineAmount(row) : 0),
    0,
  );
  const attachmentFee = listedAttachmentTotal;
  const excludedFormulaAttachmentTotal = attachments.reduce(
    (sum, attachment) => sum + (!attachment.catalog_version && formulaAttachmentExcluded(attachment)
      ? attachmentLineAmount(attachment) : 0),
    0,
  );
  const formulaAttachmentFee = attachmentFee;
  const componentKeys = [
    "material_cost", "auxiliary_cost", "labor_cost", "spray_cost", "management_fee",
  ];
  const basePrice = moneySum(componentKeys.map(key=>quote[key]));
  const originalPriceAttachmentTotal = attachments.reduce(
    (sum, attachment) => sum + (!formulaAttachmentExcluded(attachment)
      && attachmentExcludedFromDiscount(attachment)
      ? effectiveFormulaAttachmentLineAmount(attachment, cabinetQuantity, gangedCount) : 0),
    0,
  );
  const effectiveAttachmentTotal = attachments.filter((attachment) => !formulaAttachmentExcluded(attachment))
    .reduce((sum,row)=>sum+effectiveFormulaAttachmentLineAmount(row,cabinetQuantity,gangedCount),0);
  const discountedAttachmentTotal = attachments.reduce(
    (sum, attachment) => sum + (!formulaAttachmentExcluded(attachment)
      && !attachmentExcludedFromDiscount(attachment)
      ? effectiveFormulaAttachmentLineAmount(attachment, cabinetQuantity, gangedCount) : 0),
    0,
  );
  const equivalentUnitTotal = moneySum([
    moneyProduct(moneySum([basePrice, ...attachments.filter(row => !formulaAttachmentExcluded(row)
      && !attachmentExcludedFromDiscount(row)).map(formulaAttachmentLineAmount)]), discount),
    ...attachments.filter(row => !formulaAttachmentExcluded(row) && attachmentExcludedFromDiscount(row))
      .map(formulaAttachmentLineAmount), freightFee,
  ]);
  const lineTotal = moneyProduct(equivalentUnitTotal, cabinetQuantity);
  return {
    basePrice,
    attachmentFee: formulaAttachmentFee,
    excludedFormulaAttachmentTotal,
    listedAttachmentTotal,
    effectiveAttachmentTotal,
    discountedAttachmentTotal,
    originalPriceAttachmentTotal,
    cabinetQuantity,
    gangedCabinetCount: gangedCount,
    discount,
    freightFee,
    freightTotal,
    lineTotal,
    equivalentUnitTotal,
  };
};

// Public non-ganged quote rows use a per-cabinet unit price and multiply that
// price by the operator-entered cabinet quantity. Ganged rows remain one
// complete assembly per public row, so their right-side audit amounts are
// calculated as order totals before deriving the equivalent unit price.
const quickPublicLineBreakdown = (item = {}) => {
  const quote = item.quick || {};
  const attachments = item.attachments || [];
  const cabinetQuantity = asNumber(item.quantity || 1);
  const gangedCount = gangedCabinetCount(item);
  const discount = asNumber(item.quick_discount ?? 1);
  const freightFee = Math.max(0, asNumber(item.freight_fee ?? item.freight));
  return quickOrderLineBreakdown({
      quote,
      attachments,
      discount,
      cabinetQuantity,
      gangedCabinetCount: gangedCount,
      freightFee,
      materialDifference: item.quote_display?.material_difference ?? 0,
    });
};

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

const DOOR_PHRASE_PATTERN = /前(?:单|双)开门后(?:背板|单开门|双开门)|前后(?:单|双)开门|前(?:单|双)开门/u;
const DOOR_PHRASES_BY_COUNTS = new Map([
  ["1/0", "前单开门"],
  ["0/1", "前双开门"],
  ["2/0", "前后单开门"],
  ["0/2", "前后双开门"],
  ["1/1", "前单开门后双开门"],
]);

const doorPhraseForItem = (item = {}) => {
  const hasCounts = ["single_door_count", "double_door_count"].every(
    (key) => Object.hasOwn(item, key) && item[key] !== null && item[key] !== "",
  );
  if (hasCounts) {
    const single = Number(item.single_door_count);
    const double = Number(item.double_door_count);
    if (Number.isInteger(single) && Number.isInteger(double)) {
      const phrase = DOOR_PHRASES_BY_COUNTS.get(`${single}/${double}`);
      if (phrase) return phrase;
    }
  }
  const variant = String(item.variant_name || item.variant_code || "");
  if (/双|DOUBLE/i.test(variant)) return "前双开门";
  if (/单|SINGLE/i.test(variant)) return "前单开门";
  return "";
};

const replaceDoorConfigurationPhrase = (remark, item = {}) => {
  const text = String(remark || "");
  const expected = doorPhraseForItem(item);
  return expected && DOOR_PHRASE_PATTERN.test(text)
    ? text.replace(DOOR_PHRASE_PATTERN, expected)
    : text;
};

// Convert raw OCR technical requirements into the concise configuration
// wording approved for the formal quotation.  This fallback also upgrades
// draft rows created by older client builds at export time.
const standardizedRemark = (item = {}) => {
  const stored = replaceDoorConfigurationPhrase(
    String(item.final_remark ?? item.notes ?? "").trim(),
    item,
  );
  if (isDrawingSourcedQuoteItem(item)) return stored;
  const source = replaceDoorConfigurationPhrase(
    String(item.source_ocr_remark || stored).trim(),
    item,
  );
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
  const doorPhrase = doorPhraseForItem(item) || source.match(DOOR_PHRASE_PATTERN)?.[0];
  if (doorPhrase) parts.push(doorPhrase);
  const seen = new Set();
  for (const attachment of item.attachments || []) {
    const wording = attachmentRemark({
      ...attachment,
      quantity: effectiveAttachmentQuantity(
        attachment, item.quantity || 1, gangedCabinetCount(item),
      ),
    });
    if (wording && !seen.has(wording)) { parts.push(wording); seen.add(wording); }
  }
  return `${parts.filter(Boolean).join("，").replace(/[，。；;\s]+$/u, "")}。`;
};

function fillSheet(sheet, method) {
  const items = payload.items || [];
  const lastColumn = method === "formula" ? formulaLastColumn : quickLastColumn;
  const columnCount = method === "formula" ? formulaDiscountColumnIndex : quickDiscountColumnIndex;
  const discountColumn = method === "formula" ? formulaLastColumn : quickLastColumn;
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
  sheet.getRange('D3').values = [['订单性质']];
  sheet.getRange('E3').values = [[orderNatureLabel(payload.order_nature)]];
  sheet.getRange("B4").values = [[payload.company_name || ""]];
  let subtotal = 0;
  items.forEach((item, index) => {
    const row = firstRow + index;
    const display = quoteDisplay(item);
    validateQuoteDisplay(item);
    const discount = asNumber((method === "formula"
      ? item.formula_discount : display?.discount ?? item.quick_discount) ?? 1);
    const attachments = method === "quick" ? quickExportAttachments(item) : (item.attachments || []);
    const qty = asNumber(display?.quantity ?? item.quantity ?? 1);
    const quickAuditItem = method === "quick" ? {
      ...item,
      attachments,
      quantity: qty,
      quick_discount: discount,
      quick: quickExportQuote(item),
    } : null;
    const quote = method === "formula" ? item.formula : quickAuditItem.quick;
    const gangedCount = gangedCabinetCount(item);
    const isGanged = gangedCount > 1;
    const unitSet = item.pricing_basis === PRICING_BASIS;
    const auditCabinetQuantity = unitSet ? 1 : isGanged ? qty : 1;
    const auditGangedCount = unitSet ? 1 : isGanged ? gangedCount : 1;
    const quickBreakdown = method === "quick"
      ? quickPublicLineBreakdown(quickAuditItem)
      : null;
    const quickOriginalBreakdown = method === "quick"
      ? quickPublicLineBreakdown({ ...quickAuditItem, quick_discount: 1 })
      : null;
    const formulaBreakdown = method === "formula" ? formulaOrderLineBreakdown(item) : null;
    const unitCost = method === "quick" && hasFiniteNumber(display?.unit_price)
      ? Number(display.unit_price)
      : method === "quick"
        ? quickBreakdown.equivalentUnitTotal
      : formulaBreakdown.equivalentUnitTotal;
    const lineTotal = method === "quick" && hasFiniteNumber(display?.total)
      ? Number(display.total)
      : method === "quick" ? quickBreakdown.lineTotal : formulaBreakdown.lineTotal;
    subtotal = moneySum([subtotal, lineTotal]);
    // final_remark is the operator-confirmed wording shown on the Remarks page.
    // Keep notes as a backward-compatible fallback for older saved drafts.
    const note = display && Object.hasOwn(display, "remark")
      ? String(display.remark ?? "") : standardizedRemark(item);
    // 规格型号优先使用人工确认的 W*D*H 高度表达式；未提供时按
    // 内部 W/H/D 尺寸回退，不能再被图号或产品型号覆盖。
    const spec = String(display?.specification || quoteSpecification(item));
    const values = Array(columnCount).fill("");
    values[0] = index + 1;
    values[1] = display && Object.hasOwn(display, "name")
      ? String(display.name ?? "")
      : drawingNameBeforeChinese(item.name || item.source_pdf_name || item.product_family || item.product_code);
    values[2] = spec;
    values[3] = qty;
    values[4] = String(display?.unit || "台");
    values[5] = unitCost;
    values[6] = lineTotal;
    values[7] = note;
    const extras = method === "quick"
      ? quickAttachmentAmounts(
        attachments,
        auditCabinetQuantity,
        auditGangedCount,
        Array.isArray(display?.attachments),
      )
      : attachmentAmounts(
        attachments, discount, method, auditCabinetQuantity, auditGangedCount,
      );
    for (const [columnIndex, amount] of Object.entries(extras)) values[Number(columnIndex) - 1] = amount;
    // Export the same attachment aggregate that is visible in the editor.
    const attachmentFee = method === "formula"
      ? attachments.reduce(
        (sum, attachment) => sum + (!formulaAttachmentExcluded(attachment)
          ? formulaAttachmentLineAmount(attachment) : 0),
        0,
      )
      : attachmentTotalFromItems(attachments);
    if (method === "formula") {
      // Keep the five component columns reconcilable with the discounted
      // formula-method amount. Non-ganged rows show one-cabinet costs; ganged
      // rows show the complete order costs for the entered assembly quantity.
      const componentMultiplier = unitSet ? 1 : isGanged ? qty : 1;
      values[11] = asNumber(quote?.material_cost) * discount * componentMultiplier;
      values[12] = asNumber(quote?.auxiliary_cost) * discount * componentMultiplier;
      values[13] = asNumber(quote?.labor_cost) * discount * componentMultiplier;
      values[14] = asNumber(quote?.spray_cost) * discount * componentMultiplier;
      values[15] = asNumber(quote?.management_fee) * discount * componentMultiplier;
      // Freight is the final dynamic attachment-detail column and is never
      // discounted; the following column records the formula discount.
      values[formulaFreightColumnIndex - 1] = (unitSet ? formulaBreakdown.freightFee : formulaBreakdown.freightTotal) || "";
      values[formulaDiscountColumnIndex - 1] = discount;
    } else {
      const listedAmount = attachmentTotalFromItems(attachments);
      // Every selected attachment name has one original-price audit column.
      // The fixed delta column reconciles authoritative attachment totals.
      if (quickOtherColumnIndex) {
        const difference = (attachmentFee - listedAmount)
          * auditCabinetQuantity * auditGangedCount;
        values[quickOtherColumnIndex - 1] = Math.abs(difference) > 0.000001 ? difference : "";
      }
      values[11] = quickBreakdown.basePrice * auditCabinetQuantity;
      values[quickFreightColumnIndex - 1] = (unitSet ? quickBreakdown.freightFee : quickBreakdown.freightTotal) || "";
      if (quickMaterialColumnIndex) values[quickMaterialColumnIndex - 1] = money(display?.material_difference || 0);
      values[quickDiscountColumnIndex - 1] = discount;
      const populatedCellReferences = (columns) => columns
        .filter(([, valueIndex]) => {
          const value = values[valueIndex];
          return value !== "" && value !== null && value !== undefined
            && Number.isFinite(Number(value)) && Number(value) !== 0;
        })
        .map(([column]) => `${column}${row}`);
      const discountedColumns = [["L", 11]];
      const originalColumns = [];
      for (const name of quickAttachmentNames) {
        const index = quickNameColumnByName.get(name);
        const sample = attachments.find((attachment) => quickAttachmentName(attachment) === name);
        const target = [col(index), index - 1];
        if (sample && quickDiscountCategory(sample)) discountedColumns.push(target);
        else originalColumns.push(target);
      }
      if (quickOtherColumnIndex) {
        originalColumns.push([col(quickOtherColumnIndex), quickOtherColumnIndex - 1]);
      }
      const discountedCells = populatedCellReferences(discountedColumns);
      const originalPriceCells = populatedCellReferences(originalColumns);
      // J and K are real, editable Excel formulas. Every amount references its
      // corresponding source cell; changing an original price or the discount
      // therefore recalculates both comparisons in Excel/WPS automatically.
      const formulaParts = [];
      const originalFormulaParts = [];
      const originalCells = [...discountedCells, ...originalPriceCells];
      if (originalCells.length) originalFormulaParts.push(originalCells.join("+"));
      if (discountedCells.length) {
        const discountedExpression = discountedCells.length === 1
          ? discountedCells[0]
          : `(${discountedCells.join("+")})`;
        const discountedFormula = `${discountedExpression}*${col(quickDiscountColumnIndex)}${row}`;
        // Preserve the historical ganged compatibility formula unchanged.
        // Current per-set rows round the discounted unit price before adding
        // original-price attachments and freight, matching the desktop client.
        formulaParts.push(!unitSet && isGanged ? discountedFormula : `ROUND(${discountedFormula},2)`);
      }
      if (originalPriceCells.length) formulaParts.push(originalPriceCells.join("+"));
      if (quickBreakdown.freightTotal) {
        const freightCell = `${col(quickFreightColumnIndex)}${row}`;
        const freightExpression = unitSet || isGanged ? freightCell : `${freightCell}/${qty || 1}`;
        originalFormulaParts.push(freightExpression);
        formulaParts.push(freightExpression);
      }
      if (quickMaterialColumnIndex) {
        const materialCell = `${col(quickMaterialColumnIndex)}${row}`;
        originalFormulaParts.push(materialCell);
        formulaParts.push(materialCell);
      }
      const originalFormula = originalFormulaParts.join("+") || "0";
      const formula = formulaParts.join("+") || "0";
      const originalPriceFormula = !unitSet && isGanged ? `(${originalFormula})/D${row}` : `ROUND(${originalFormula},2)`;
      const discountedPriceFormula = !unitSet && isGanged ? `(${formula})/D${row}` : `ROUND(${formula},2)`;
      values[9] = {
        formula: originalPriceFormula,
        result: quickOriginalBreakdown.equivalentUnitTotal,
      };
      values[10] = {
        formula: unitSetWorkbook ? `ROUND(J${row}*D${row},2)` : discountedPriceFormula,
        result: unitSetWorkbook ? moneyProduct(quickOriginalBreakdown.equivalentUnitTotal, qty) : quickBreakdown.equivalentUnitTotal,
      };
    }
    sheet.getRange(`A${row}:${lastColumn}${row}`).values = [values];
    sheet.getRange(`H${row}`).format.wrapText = true;
    sheet.getRange(`H${row}`).format.verticalAlignment = "middle";
  });
  sheet.getRange(`B${subtotalRow}`).values = [["合计"]];
  sheet.getRange(`G${subtotalRow}`).values = [[subtotal]];
  sheet.getRange(`A${subtotalRow}:${lastColumn}${subtotalRow}`).format.font = { bold: true };
  sheet.getRange(`F${firstRow}:G${subtotalRow}`).format.numberFormat = "#,##0.00";
  sheet.getRange(`L${firstRow}:${col(columnCount - 1)}${dataEnd}`).format.numberFormat = "#,##0.00";
  if (method === "quick") {
    sheet.getRange(`J${firstRow}:K${dataEnd}`).format.numberFormat = "#,##0.00";
    sheet.getRange(`J${firstRow}:K${dataEnd}`).format.horizontalAlignment = "center";
  }
  sheet.getRange(`${discountColumn}${firstRow}:${discountColumn}${dataEnd}`).format.numberFormat = "0.00";
}

let costDetailLastRow = 7;

function buildFormulaCostDetailSheet() {
  const sheet = attachRangeApi(workbook.addWorksheet("成本明细"));
  sheet.views = [{ showGridLines: false }];
  const items = payload.items || [];
  const headers = [
    "柜号", "名称", "规格型号", "成本类别", "明细项目", "规格/说明",
    "计算公式/计价依据", "最终用量", "单位", "单价（元）", "本项金额（元）",
    "柜体数量/倍率", "行金额（元）", "数据来源", "备注",
  ];
  const lastColumn = col(headers.length);
  const firstDataRow = 6;
  const detailRows = [];
  const detailStyles = [];

  const addDetail = (itemIndex, item, category, detailName, spec, basis, usage, unit,
    unitPrice, unitAmount, source, note = "", kind = "detail", quantityMultiplier = null,
    cabinetLabel = null) => {
    const cabinetQuantity = quantityMultiplier === null
      ? asNumber(item.quantity || 1) : asNumber(quantityMultiplier);
    detailRows.push([
      cabinetLabel ?? itemIndex + 1,
      drawingNameBeforeChinese(
        item.source_pdf_name || item.name || item.product_family || item.product_code,
      ),
      quoteSpecification(item),
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

  // A ganged formula snapshot contains one formula_cost per child cabinet.
  // Expand material rows from those child snapshots instead of displaying
  // only the aggregate parent material row.  Other cost categories retain
  // their existing aggregate/detail behaviour below.
  const addMaterialRows = (itemIndex, item, quote, cabinetLabel = null) => {
    const materialPartDetails = Array.isArray(quote.cabinet_material_part_details)
      ? quote.cabinet_material_part_details : [];
    const materialDetails = Array.isArray(quote.material_details) ? quote.material_details : [];
    if (materialPartDetails.length) {
      for (const part of materialPartDetails) {
        const netWeight = optionalNumber(part.net_weight_kg);
        const billableWeight = optionalNumber(part.billable_weight_kg);
        const wasteFactor = optionalNumber(part.waste_factor ?? quote.waste_factor);
        const unitPrice = optionalNumber(part.material_unit_price);
        const amount = asNumber(part.material_cost);
        addDetail(
          itemIndex, item, "材料成本", part.part_name || `${part.material_code || "材料"}零件`,
          `${part.material_code || ""} / ${part.sheet_thickness_mm ?? ""} mm`,
          `面积 ${part.area_m2 ?? ""} m² × 料厚 ${part.sheet_thickness_mm ?? ""} mm × 内部数量 ${part.internal_quantity ?? ""} × 密度 ${part.density_g_cm3 ?? ""} g/cm³ = 净重 ${(netWeight ?? 0).toFixed(6)} kg；× 废料系数 ${(wasteFactor ?? 1).toFixed(3)} = 计价重 ${(billableWeight ?? 0).toFixed(6)} kg；× ${(unitPrice ?? 0).toFixed(4)} 元/kg = ${amount.toFixed(2)} 元`,
          billableWeight, "kg", unitPrice, amount,
          `${quote.cabinet_material_version || "最新柜体材料明细"} / ${part.source_sheet || ""} 第 ${part.source_row_no || ""} 行`,
          `面积公式：${part.area_formula || ""}；最终用量为每台柜体计价重量。`,
          "detail", null, cabinetLabel,
        );
      }
      return true;
    }
    if (materialDetails.length) {
      for (const material of materialDetails) {
        const netWeight = optionalNumber(material.net_weight_kg);
        const billableWeight = optionalNumber(material.billable_weight_kg);
        const wasteFactor = optionalNumber(quote.waste_factor ?? material.waste_factor);
        const appliesWasteFactor = quote.waste_factor_applied !== false;
        const unitPrice = optionalNumber(material.material_unit_price);
        const amount = asNumber(material.material_cost);
        addDetail(
          itemIndex, item, "材料成本", `${material.material_code || "材料"}板材`,
          material.material_code || "",
          netWeight !== null && billableWeight !== null && unitPrice !== null
            ? (appliesWasteFactor
              ? `净重 ${netWeight.toFixed(6)} kg × 废料系数 ${(wasteFactor ?? 1).toFixed(3)} = 计价重 ${billableWeight.toFixed(6)} kg；× ${unitPrice.toFixed(4)} 元/kg = ${amount.toFixed(2)} 元`
              : `经验重量 ${netWeight.toFixed(6)} kg（不乘损耗系数）× ${unitPrice.toFixed(4)} 元/kg = ${amount.toFixed(2)} 元`)
            : (appliesWasteFactor ? "净材料重量 × 废料系数 × 材料单价" : "经验重量（不乘损耗系数）× 材料单价"),
          billableWeight, "kg", unitPrice, amount,
          quote.cabinet_material_version || "最新柜体材料明细 / 数据库材料价格历史",
          appliesWasteFactor
            ? "最终用量为每台柜体计价材料重量；柜体数量在行金额中另乘。"
            : "经验重量按源表或非标尺寸周长比例计算，不乘损耗系数；柜体数量在行金额中另乘。",
          "detail", null, cabinetLabel,
        );
      }
      return true;
    }
    const materialCost = asNumber(quote.material_cost);
    const materialUnitPrice = optionalNumber(quote.material_unit_price);
    const correctedWeight = optionalNumber(quote.corrected_material_weight_kg);
    const weight = correctedWeight !== null
      ? correctedWeight
      : (materialUnitPrice !== null && materialUnitPrice > 0 ? materialCost / materialUnitPrice : null);
    addDetail(
      itemIndex, item, "材料成本", `${item.material_code || "材料"}板材`,
      item.material_code || "", weight !== null && materialUnitPrice !== null
        ? `${weight.toFixed(6)} kg × ${materialUnitPrice.toFixed(4)} 元/kg = ${materialCost.toFixed(2)} 元`
        : "修正后材料重量 × 材料单价",
      weight, "kg", materialUnitPrice, materialCost, "历史公式法快照",
      "旧报价缺少新版柜体材料分材质明细", "detail", null, cabinetLabel,
    );
    return true;
  };

  const addAuxiliaryRows = (itemIndex, item, quote, cabinetLabel = null) => {
    const auxiliaryCost = asNumber(quote.auxiliary_cost);
    const auxiliary = item.auxiliary_detail || {};
    const auxiliaryLines = Array.isArray(quote.cabinet_auxiliary_lines)
      ? quote.cabinet_auxiliary_lines : (Array.isArray(auxiliary.lines) ? auxiliary.lines : []);
    let auxiliaryLineSum = 0;
    for (const line of auxiliaryLines) {
      const quantity = asNumber(line.internal_quantity ?? line.quantity);
      const price = Number(line.unit_price);
      const amount = Number.isFinite(Number(line.line_total))
        ? Number(line.line_total)
        : (Number.isFinite(price) ? quantity * price : 0);
      auxiliaryLineSum += amount;
      addDetail(
        itemIndex, item, "辅材成本", line.item_name || line.item_code || "辅材",
        [line.spec_model, line.material_name].filter(Boolean).join(" / "),
        line.length_per_piece_m == null
          ? `${quantity} 件 × ${Number.isFinite(price) ? price.toFixed(4) : ""} 元/件 = ${amount.toFixed(2)} 元`
          : `${line.length_per_piece_m} m/件 × ${quantity} 件 × ${Number.isFinite(price) ? price.toFixed(4) : ""} 元/m`
            + (asNumber(line.spray_area_m2) > 0 ? `；喷塑 ${line.spray_area_m2} m² × ${asNumber(line.spray_unit_price).toFixed(4)} 元/m²` : "")
            + ` = ${amount.toFixed(2)} 元`,
        quantity, line.unit || "件", Number.isFinite(price) ? price : null, amount,
        quote.cabinet_auxiliary_version
          ? `${quote.cabinet_auxiliary_version} / ${line.source_sheet || ""} 第 ${line.source_row_no || ""} 行`
          : ([auxiliary.source_file, auxiliary.source_sheet || line.source_sheet].filter(Boolean).join(" / ") || "数据库辅材 BOM"),
        [line.length_formula ? `长度公式：${line.length_formula}` : "", line.notes || ""].filter(Boolean).join("；"),
        "detail", null, cabinetLabel,
      );
    }
    if (!auxiliaryLines.length) {
      addDetail(
        itemIndex, item, "辅材成本", "辅材成本（经验值）", "无 BOM 明细",
        "数据库辅材经验值（同柜型尺寸规则）", 1, "项", auxiliaryCost, auxiliaryCost,
        "数据库辅材经验值", "该柜型按经验值计价", "detail", null, cabinetLabel,
      );
      auxiliaryLineSum = auxiliaryCost;
    } else if (Math.abs(auxiliaryCost - auxiliaryLineSum) > 0.01) {
      const adjustment = auxiliaryCost - auxiliaryLineSum;
      addDetail(
        itemIndex, item, "辅材成本", "BOM 汇总调整", "使 BOM 明细与公式法辅材成本一致",
        `${auxiliaryCost.toFixed(2)} - ${auxiliaryLineSum.toFixed(2)} = ${adjustment.toFixed(2)} 元`,
        1, "项", adjustment, adjustment, "数据库公式法计算结果",
        "源表 BOM 合计与当前计价结果的差额", "adjustment", null, cabinetLabel,
      );
    }
    return true;
  };

  items.forEach((item, itemIndex) => {
    const quote = item.formula || {};
    const materialCost = asNumber(quote.material_cost);
    const gangedMaterialCosts = Array.isArray(quote.ganged_cabinet_costs)
      ? quote.ganged_cabinet_costs.filter((child) => child && typeof child.formula_cost === "object")
      : [];
    let materialExpanded = false;
    if (gangedMaterialCosts.length) {
      for (const [position, child] of gangedMaterialCosts.entries()) {
        const cabinetIndex = Number.isFinite(Number(child.cabinet_index))
          ? Number(child.cabinet_index) : position + 1;
        const childSpecification = String(child.model_code || "").trim();
        const childItem = {
          ...item,
          model_code: childSpecification || item.model_code,
          specification: childSpecification || item.specification,
        };
        materialExpanded = addMaterialRows(
          itemIndex, childItem, child.formula_cost,
          `${itemIndex + 1}-子柜${cabinetIndex}`,
        ) || materialExpanded;
      }
    }
    if (!materialExpanded) addMaterialRows(itemIndex, item, quote);

    const auxiliaryCost = asNumber(quote.auxiliary_cost);
    let auxiliaryExpanded = false;
    if (gangedMaterialCosts.length) {
      for (const [position, child] of gangedMaterialCosts.entries()) {
        const cabinetIndex = Number.isFinite(Number(child.cabinet_index))
          ? Number(child.cabinet_index) : position + 1;
        const childSpecification = String(child.model_code || "").trim();
        const childItem = {
          ...item,
          model_code: childSpecification || item.model_code,
          specification: childSpecification || item.specification,
        };
        auxiliaryExpanded = addAuxiliaryRows(
          itemIndex, childItem, child.formula_cost,
          `${itemIndex + 1}-子柜${cabinetIndex}`,
        ) || auxiliaryExpanded;
      }
    }
    if (!auxiliaryExpanded) addAuxiliaryRows(itemIndex, item, quote);

    const laborCost = asNumber(quote.labor_cost);
    if (quote.cabinet_labor_version) {
      const laborWeight = optionalNumber(quote.labor_billable_weight_kg);
      addDetail(
        itemIndex, item, "人工成本", "柜体人工成本", quote.labor_method || "最新人工规则",
        quote.labor_source_formula
          ? `${quote.labor_source_formula}；计人工重量 ${laborWeight?.toFixed(6) ?? ""} kg`
          : (quote.labor_perimeter_ratio
            ? `固定人工按非标尺寸周长比例 ${asNumber(quote.labor_perimeter_ratio).toFixed(6)} 修正`
            : "产品、型号、材质及尺寸固定人工"),
        1, "项", laborCost, laborCost,
        `${quote.cabinet_labor_version} / ${quote.labor_source_sheet || ""} 第 ${quote.labor_source_row_no || ""} 行`,
        (quote.labor_excluded_part_names || []).length
          ? `计人工重量已扣除：${quote.labor_excluded_part_names.join("、")}` : "",
      );
    } else {
      addDetail(
        itemIndex, item, "人工成本", "人工成本（经验值）", "同柜型/同材质/最近尺寸",
        "数据库人工经验值（已含人工成本修正系数）", 1, "项", laborCost, laborCost,
        "数据库人工经验值", "非精确尺寸按同柜型最近尺寸及周长比例修正",
      );
    }

    const lineBreakdown = formulaOrderLineBreakdown(item);
    const attachmentCost = lineBreakdown.attachmentFee;
    const attachments = Array.isArray(item.attachments) ? item.attachments : [];
    let attachmentLineSum = 0;
    for (const [attachmentIndex,attachment] of attachments.entries()) {
      const selectedQuantity = asNumber(attachment.quantity || 1);
      const splitCount = gangedCabinetCount(item);
      const quantity = effectiveAttachmentQuantity(
        attachment, item.quantity || 1, splitCount,
      );
      const price = attachmentUnitPrice(attachment);
      const selectedAmount = formulaAttachmentLineAmount(attachment);
      const amount = effectiveFormulaAttachmentLineAmount(
        attachment, item.quantity || 1, splitCount,
      );
      const omittedFromFormula = formulaAttachmentExcluded(attachment);
      const formulaSelectedAmount = omittedFromFormula ? 0 : selectedAmount;
      const formulaAmount = omittedFromFormula ? 0 : amount;
      attachmentLineSum += formulaSelectedAmount;
      const allocation=quote.cost_allocation;
      const allocated=allocation?.complete?allocation.lines.find(line=>line.index===attachmentIndex):null;
      if(allocated?.method==='FORMULA'&&!omittedFromFormula){
        const labels={material_cost:'材料成本',spray_cost:'喷塑费用',auxiliary_cost:'辅材成本',labor_cost:'人工成本'};
        for(const [key,component] of Object.entries(allocated.components)){
          const count=asNumber(item.quantity||1),lineAmount=moneyProduct(component.amount,count);
          addDetail(itemIndex,item,labels[key],`${allocated.name}－${labels[key]}`,allocated.specification,
            `${component.formula}；单台/套 ${component.amount.toFixed(2)} 元 × ${count}`,
            allocated.quantity*count,allocated.unit,component.unit_cost,lineAmount,
            '已保存附件公式成本分项','公式附件分项归类，不重复计入附件成本','detail',1);
        }
        continue;
      }
      const multiplier = selectedQuantity ? quantity / selectedQuantity : 1;
      const signedPrice = quantity ? formulaAmount / quantity : (omittedFromFormula ? 0 : price);
      const componentBasis = attachmentFormulaCostBasis(attachment);
      addDetail(
        itemIndex, item, "附件成本", attachment.item_name || attachment.model_code || "附件",
        [attachment.model_code, attachment.variant, attachment.notes].filter(Boolean).join(" / "),
        omittedFromFormula
          ? (attachment.catalog_version ? '当前产品无适用成本规则，仅快速报价；见附件双报价明细'
            : `原附件金额 ${amount.toFixed(2)} 元；一级分类为门变形，公式法不计费`)
          : `${componentBasis ? `${componentBasis}；` : ""}${selectedQuantity} × 柜体倍率 ${multiplier} = 最终数量 ${quantity}；`
            + `${quantity} × ${signedPrice.toFixed(2)} = ${formulaAmount.toFixed(2)} 元`,
        quantity, attachment.unit || "件", signedPrice, formulaAmount,
        attachment.price_source || "数据库附件价格表",
        omittedFromFormula
          ? "仅快速报价计费；公式法附件费用为 0"
          : attachmentExcludedFromDiscount(attachment)
          ? "原价附件：不参与公式法或快速报价折扣"
          : attachment.ganged_fixed_base_match
          ? "按子柜分别匹配；仅随整套柜体数量变化"
          : (attachmentUsesCabinetQuantity(attachment)
            ? "选择数量随柜体数量变化" : "人工数量不受柜体数量影响"),
        "detail", 1,
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
    const productArea = optionalNumber(quote.product_area_m2);
    const sprayUnitPrice = optionalNumber(quote.spray_unit_price);
    const sprayPartDetails = Array.isArray(quote.cabinet_spray_part_details)
      ? quote.cabinet_spray_part_details : [];
    if (sprayPartDetails.length && sprayUnitPrice !== null) {
      let allocatedSprayCost = 0;
      sprayPartDetails.forEach((part, partIndex) => {
        const areaPerPiece = asNumber(part.area_per_piece_m2);
        const internalQuantity = asNumber(part.internal_quantity);
        const totalArea = asNumber(part.total_area_m2);
        const calculatedAmount = totalArea * sprayUnitPrice;
        const amount = partIndex === sprayPartDetails.length - 1
          ? sprayCost - allocatedSprayCost : calculatedAmount;
        allocatedSprayCost += amount;
        addDetail(
          itemIndex, item, "喷塑费用", part.part_name || "柜体零件", "面积公式 × 内部数量",
          `${areaPerPiece.toFixed(8)} m²/件 × ${internalQuantity} 件 × ${sprayUnitPrice.toFixed(4)} 元/m² = ${amount.toFixed(2)} 元`,
          totalArea, "m²", sprayUnitPrice, amount,
          `${quote.cabinet_spray_version || "最新柜体喷塑明细"} / ${part.source_sheet || ""} 第 ${part.source_row_no || ""} 行`,
          `面积公式：${part.area_formula || ""}；最终一行包含整柜喷塑成本的舍入差额。`,
        );
      });
    } else if (productArea !== null && sprayUnitPrice !== null) {
      addDetail(
        itemIndex, item, "喷塑费用", `${item.coating_type || "喷塑"}`, "产品喷涂面积",
        `${productArea.toFixed(6)} m² × ${sprayUnitPrice.toFixed(4)} 元/m² = ${sprayCost.toFixed(2)} 元`,
        productArea, "m²", sprayUnitPrice, sprayCost, "数据库喷塑单价历史", "产品面积由柜体喷塑目录计算",
      );
    } else {
      addDetail(
        itemIndex, item, "喷塑费用", `${item.coating_type || "喷塑"}（经验值）`, "直接喷塑价格",
        "数据库喷塑经验值（无面积公式）", 1, "项", sprayCost, sprayCost,
        "数据库喷塑经验值", "经验值柜型按同柜型最近尺寸及周长比例修正",
      );
    }

    const managementCost = asNumber(quote.management_fee);
    const managementRate = MANAGEMENT_FEE_RATE;
    const managementBase = asNumber(quote.management_fee_base);
    const managementTerms = [materialCost, auxiliaryCost, laborCost, attachmentCost, sprayCost,
      Math.max(0, asNumber(item.freight_fee ?? item.freight))];
    const managementExpression = `(${managementTerms.map(value=>value.toFixed(2)).join(' + ')})`;
    addDetail(
      itemIndex, item, "管理费用", "管理费用",
      "材料＋辅材＋柜体人工＋附件＋喷涂＋运费的 6%",
      `${managementExpression} × ${managementRate} = ${managementCost.toFixed(2)} 元`,
      managementBase, "元", managementRate, managementCost, "系统统一公式",
      "管理费用＝（材料＋辅材＋柜体人工＋附件＋喷涂＋运费）×0.06；不含管理费本身",
    );

    const freightFee = Math.max(0, asNumber(item.freight_fee ?? item.freight));
    if (freightFee > 0) {
      addDetail(
        itemIndex, item, "运费", "运费", "人工输入",
        `${freightFee.toFixed(2)} 元 × ${asNumber(item.quantity || 1)} 台`,
        1, "项", freightFee, freightFee, "人工输入",
        "运费不参与公式法或快速报价折扣",
      );
    }

    const componentTotal = materialCost + auxiliaryCost + laborCost + attachmentCost + sprayCost + managementCost;
    const formulaCost = asNumber(quote.total_cost) - lineBreakdown.excludedFormulaAttachmentTotal;
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
      `柜体基础成本按 ${lineBreakdown.cabinetQuantity} 台计算；附件按最终数量计价；`
        + `原价附件 ${lineBreakdown.originalPriceAttachmentTotal.toFixed(2)} 元不参与折扣；`
        + `运费 ${lineBreakdown.freightFee.toFixed(2)} 元/台且不参与折扣；`
        + `订单行合计 ${lineBreakdown.lineTotal.toFixed(2)} 元`,
      1, "台", formulaCost, lineBreakdown.equivalentUnitTotal, "公式法报价结果",
      `折后单价；共 ${asNumber(item.quantity || 1)} 台`, "subtotal",
    );
  });

  const subtotalRow = firstDataRow + detailRows.length;
  costDetailLastRow = subtotalRow;

  sheet.mergeCells(`A1:${lastColumn}1`);
  sheet.getRange("A1").values = [["公式法报价成本明细"]];
  sheet.getRange("A2").values = [["报价编号"]];
  sheet.getRange("B2").values = [[payload.quote_id || ""]];
  sheet.getRange('A4').values = [['订单性质']];
  sheet.getRange('B4').values = [[orderNatureLabel(payload.order_nature)]];
  sheet.getRange("D2").values = [["报价日期"]];
  sheet.getRange("E2").values = [[payload.quote_date || ""]];
  sheet.getRange("G2").values = [["客户"]];
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
  const formulaOrderTotal = items.reduce(
    (sum, item) => sum + formulaOrderLineBreakdown(item).lineTotal, 0,
  );
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

// Layout only: keep fillSheet and every pricing function above unchanged.
// Excel shares row heights across a sheet. Split its physical rows and merge
// each A:H cell over the split so the original quotation retains exactly the
// same visual heights, widths, values and styles beside the compact detail.
const quotationLayouts = new Map();
function arrangeVerticalQuotationDetails(sheet, method) {
  const clone = value => value === undefined ? undefined : structuredClone(value);
  const startColumn = method === "formula" ? 12 : 10;
  const endColumn = method === "formula" ? formulaDiscountColumnIndex : quickDiscountColumnIndex;
  const sourceRowCount = sheet.rowCount;
  const sourceColumnCount = sheet.columnCount;
  const sourceRows = new Map();
  const publicRows = new Map();
  const heights = new Map();
  const addresses = new Map();
  let nextRow = 11;
  for (let row = 1; row <= sourceRowCount; row += 1) {
    const source = sheet.getRow(row);
    const height = source.height ?? sheet.properties.defaultRowHeight ?? 15;
    const span = row < 11 ? 1 : Math.max(1, Math.ceil(height / 18));
    const first = row < 11 ? row : nextRow;
    const last = first + span - 1;
    publicRows.set(row, { first, last, height });
    if (row >= 11) nextRow = last + 1;
    sourceRows.set(row, {
      hidden: source.hidden, outlineLevel: source.outlineLevel,
      cells: Array.from({ length: 8 }, (_, column) => {
        const cell = source.getCell(column + 1);
        return { value: clone(cell.value), style: clone(cell.style) };
      }),
    });
    // 0.75pt is one pixel at normal Excel zoom. Integral-pixel subrows plus
    // one remainder preserve the original visible total after pixel rounding.
    const step = span === 1 ? height : Math.floor(height / span / 0.75) * 0.75;
    for (let fine = first; fine <= last; fine += 1) {
      heights.set(fine, fine === last ? height - step * (span - 1) : step);
    }
    for (let column = 1; column <= 8; column += 1) {
      addresses.set(`${col(column)}${row}`, `${col(column)}${first}`);
    }
  }
  const fields = Array.from({ length: endColumn - startColumn + 1 }, (_, index) => ({
    name: sheet.getCell(10, startColumn + index).text,
    sourceColumn: startColumn + index,
  }));
  const spanFor = (first, required) => {
    let last = first, height = heights.get(first) ?? 18;
    while (height + 0.001 < required) { last += 1; height += heights.get(last) ?? 18; }
    return last;
  };
  const textLines = (text, width = 38) => String(text).split(/\r?\n/).reduce((sum, line) => sum + Math.max(1,
    Math.ceil([...line].reduce((size, ch) => size + (/[^\x00-\x7f]/.test(ch) ? 2 : 1), 0) / width)), 0);
  const blocks = [];
  let cursor = 10;
  payload.items.forEach((_item, index) => {
    const sourceRow = 11 + index;
    const name = String(sourceRows.get(sourceRow).cells[1].value ?? "");
    const heading = `${String(index + 1).padStart(2, "0")} · ${name}`;
    const headerLast = spanFor(cursor, Math.max(28, textLines(heading, 18) * 12 + 4));
    const block = { index, sourceRow, headerRow: cursor, headerLast, heading, fields: [] };
    cursor = headerLast + 1;
    for (const field of fields) {
      const last = spanFor(cursor, textLines(field.name) * 12 + 2);
      const cell = sheet.getCell(sourceRow, field.sourceColumn);
      const address = `${col(startColumn + 1)}${cursor}`;
      addresses.set(cell.address, address);
      block.fields.push({ ...field, row: cursor, last, address,
        sourceAddress: cell.address, value: clone(cell.value), style: clone(cell.style) });
      cursor = last + 1;
    }
    blocks.push(block);
    cursor += 1;
  });
  const moveFormula = formula => formula.replace(/\$?([A-Z]{1,3})\$?([1-9]\d*)\b/g, (match, letters, row) => {
    const moved = addresses.get(`${letters}${row}`);
    if (!moved) return match;
    const [, targetColumn, targetRow] = /^([A-Z]+)(\d+)$/.exec(moved);
    return `${match.startsWith('$') ? '$' : ''}${targetColumn}${match.includes('$' + row) ? '$' : ''}${targetRow}`;
  });
  const moveValue = value => value && typeof value === "object" && value.formula
    ? { ...clone(value), formula: moveFormula(value.formula) } : clone(value);
  for (const merge of [...sheet.model.merges]) {
    if (Number(/\d+$/.exec(merge)[0]) >= 11) sheet.unMergeCells(merge);
  }
  sheet.spliceRows(11, sourceRowCount - 10);
  for (let row = 1; row <= 10; row += 1) {
    for (let column = 9; column <= sourceColumnCount; column += 1) {
      const cell = sheet.getCell(row, column); cell.value = null; cell.style = {};
    }
  }
  for (let sourceRow = 11; sourceRow <= sourceRowCount; sourceRow += 1) {
    const range = publicRows.get(sourceRow), source = sourceRows.get(sourceRow);
    for (let row = range.first; row <= range.last; row += 1) {
      const target = sheet.getRow(row);
      target.height = heights.get(row); target.hidden = source.hidden; target.outlineLevel = source.outlineLevel;
    }
    for (let column = 1; column <= 8; column += 1) {
      const saved = source.cells[column - 1];
      if (range.last > range.first && (saved.value != null || Object.keys(saved.style).length)) {
        sheet.mergeCells(range.first, column, range.last, column);
      }
      const cell = sheet.getCell(range.first, column);
      cell.value = moveValue(saved.value); cell.style = clone(saved.style);
    }
  }
  const line = { style: "thin", color: { argb: "FFCBD5E1" } };
  const bodyStyle = { font: { name: "Microsoft YaHei", size: 10, color: { argb: "FF1F2937" } },
    alignment: { vertical: "middle", horizontal: "left", wrapText: true },
    border: { top: clone(line), bottom: clone(line), left: clone(line), right: clone(line) } };
  const headerStyle = { ...clone(bodyStyle), font: { name: "Microsoft YaHei", size: 10, bold: true, color: { argb: "FF40566F" } },
    fill: { type: "pattern", pattern: "solid", fgColor: { argb: "FFEEF3F8" } },
    alignment: { vertical: "middle", horizontal: "center", wrapText: true } };
  const write = (first, last, column, value, style) => {
    if (last > first) sheet.mergeCells(first, column, last, column);
    const cell = sheet.getCell(first, column); cell.value = value; cell.style = clone(style);
    for (let row = first; row <= last; row += 1) {
      if (!heights.has(row)) sheet.getRow(row).height = 18;
    }
  };
  sheet.getColumn(startColumn).width = 38;
  sheet.getColumn(startColumn + 1).width = 18;
  for (const block of blocks) {
    write(block.headerRow, block.headerLast, startColumn, "项目", headerStyle);
    write(block.headerRow, block.headerLast, startColumn + 1, block.heading, headerStyle);
    for (const field of block.fields) {
      write(field.row, field.last, startColumn, field.name, bodyStyle);
      const style = { ...clone(bodyStyle), numFmt: field.style.numFmt || "#,##0.00",
        alignment: { vertical: "middle", horizontal: "right" } };
      write(field.row, field.last, startColumn + 1, moveValue(field.value), style);
    }
  }
  // Remove the old wide, empty audit columns as well as their formatting.
  if (sheet.columnCount > startColumn + 1) sheet.spliceColumns(startColumn + 2, sheet.columnCount - startColumn - 1);
  if (sheet.pageSetup.printArea) {
    sheet.pageSetup.printArea = sheet.pageSetup.printArea.replace(/([A-H])(\d+)/g,
      (_match, letter, row) => `${letter}${publicRows.get(Number(row))?.last ?? row}`);
  }
  quotationLayouts.set(sheet.name, { method, startColumn, publicRows, blocks, addresses, moveValue });
}
// Older installed clients repair freight using horizontal cell addresses.
// Only clients that understand the new layout may opt in to vertical details.
const verticalDetailsRequested = payload.quotation_detail_layout === "right_vertical_v1";
for (const [sheet, method] of [[formulaSheet, "formula"], [quickSheet, "quick"]]) {
  if (verticalDetailsRequested) arrangeVerticalQuotationDetails(sheet, method);
  else quotationLayouts.set(sheet.name, {
    method, startColumn: method === "formula" ? 12 : 10,
    publicRows: new Map(Array.from({ length: sheet.rowCount }, (_, index) =>
      [index + 1, { first: index + 1, last: index + 1, height: sheet.getRow(index + 1).height }])),
    blocks: [],
  });
}

const assertClose = (actual, expected, label) => {
  if (!Number.isFinite(Number(actual)) || Math.abs(Number(actual) - Number(expected)) > 0.01) {
    throw new Error(`${label} mismatch: expected ${expected}, got ${actual}`);
  }
};

const assertRow = (actual, expected, label) => {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label} mismatch: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
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

const assertNoWorkbookAnnotations = (buffer) => {
  const annotationPattern = /^(?:xl\/comments\d+\.xml|xl\/threadedComments\/|xl\/persons\/|xl\/drawings\/vmlDrawing\d+\.vml)/i;
  const entryNames = xlsxEntryNames(buffer);
  if (!entryNames.includes("xl/workbook.xml")) {
    throw new Error("formal quotation ZIP directory is invalid");
  }
  const annotations = entryNames.filter((name) => annotationPattern.test(name));
  if (annotations.length) {
    throw new Error(`formal quotation contains annotation objects: ${annotations.join(", ")}`);
  }
};

const verifyWorkbookContents = (candidateWorkbook) => {
  attachWorkbookRangeApi(candidateWorkbook);
  const items = payload.items || [];
  const formulaPublicHeaders = LEGACY_FORMULA_HEADERS;
  const audit = {};
  for (const [sheetName, method] of [["公式法报价单", "formula"], ["快速报价单", "quick"]]) {
    const sheet = attachRangeApi(candidateWorkbook.getWorksheet(sheetName));
    if (!sheet) throw new Error(`saved workbook is missing sheet: ${sheetName}`);
    const publicHeaders = method === "quick"
      ? LEGACY_QUICK_HEADERS
      : formulaPublicHeaders;
    assertRow(rangePlainValues(sheet, "A10:H10")[0], publicHeaders, `${sheetName} public headers`);
    assertRow(
      rangePlainValues(sheet, "F4:F8").map((row) => row[0]),
      Object.values(sellerInformation).map((value) => value || null),
      `${sheetName} seller information`,
    );
    let subtotal = 0;
    items.forEach((item, index) => {
      const row = quotationLayouts.get(sheetName).publicRows.get(11 + index).first;
      const quote = method === "formula" ? item.formula : item.quick;
      const display = quoteDisplay(item);
      const discount = asNumber((method === "formula"
        ? item.formula_discount : display?.discount ?? item.quick_discount) ?? 1);
      const quantity = asNumber(display?.quantity ?? item.quantity ?? 1);
      const lineBreakdown = method === "quick"
        ? quickPublicLineBreakdown(item)
        : formulaOrderLineBreakdown(item);
      const unitCost = method === "quick" && hasFiniteNumber(display?.unit_price)
        ? Number(display.unit_price) : lineBreakdown.equivalentUnitTotal;
      const lineTotal = method === "quick" && hasFiniteNumber(display?.total)
        ? Number(display.total) : lineBreakdown.lineTotal;
      subtotal = moneySum([subtotal, lineTotal]);
      const actual = rangePlainValues(sheet, `A${row}:H${row}`)[0];
      const expected = [
        index + 1,
        display && Object.hasOwn(display, "name")
          ? String(display.name ?? "")
          : drawingNameBeforeChinese(item.name || item.source_pdf_name || item.product_family || item.product_code),
        String(display?.specification || quoteSpecification(item)),
        quantity,
        String(display?.unit || "台"),
        unitCost,
        lineTotal,
        display && Object.hasOwn(display, "remark")
          ? String(display.remark ?? "") : standardizedRemark(item),
      ];
      assertRow(actual.slice(0, 5), expected.slice(0, 5), `${sheetName} row ${row} identity`);
      assertClose(actual[5], expected[5], `${sheetName} row ${row} unit price`);
      assertClose(actual[6], expected[6], `${sheetName} row ${row} amount`);
      if (String(actual[7] ?? "") !== expected[7]) throw new Error(`${sheetName} row ${row} remark changed`);
    });
    const layout = quotationLayouts.get(sheetName);
    const subtotalRow = layout.publicRows.get(11 + items.length).first;
    if (rangePlainValues(sheet, `B${subtotalRow}`)[0][0] !== "合计") {
      throw new Error(`${sheetName} subtotal label is missing`);
    }
    assertClose(
      rangePlainValues(sheet, `G${subtotalRow}`)[0][0],
      subtotal,
      `${sheetName} subtotal`,
    );
    audit[sheetName] = [rangePlainValues(sheet, "B10:H10")[0],
      ...items.map((_item, index) => rangePlainValues(sheet, `B${layout.publicRows.get(11 + index).first}:H${layout.publicRows.get(11 + index).first}`)[0]),
      rangePlainValues(sheet, `B${subtotalRow}:H${subtotalRow}`)[0]];
  }

  if (!verticalDetailsRequested) {
    assertRow(rangePlainValues(candidateWorkbook.getWorksheet("公式法报价单"), "L10:P10")[0],
      ["材料成本", "辅材成本", "人工成本", "喷塑费用", "管理费用"], "formula cost headers");
    assertRow(rangePlainValues(candidateWorkbook.getWorksheet("公式法报价单"), `Q10:${formulaLastColumn}10`)[0],
      formulaCostHeaders, "formula attachment-name headers");
    assertRow(rangePlainValues(candidateWorkbook.getWorksheet("快速报价单"), `J10:${quickLastColumn}10`)[0],
      quickCostHeaders, "quick cost headers");
  }
  audit.quotation_layout = {};
  for (const [name, layout] of quotationLayouts) {
    const sheet = candidateWorkbook.getWorksheet(name);
    for (const block of layout.blocks) {
      assertRow([sheet.getCell(block.headerRow, layout.startColumn).text,
        sheet.getCell(block.headerRow, layout.startColumn + 1).text], ["项目", block.heading], `${name} detail identity`);
      for (const field of block.fields) {
        if (sheet.getCell(field.row, layout.startColumn).text !== field.name) throw new Error(`${name} detail label changed`);
        const actual = sheet.getCell(field.address).value;
        const expected = layout.moveValue(field.value);
        if (JSON.stringify(actual ?? null) !== JSON.stringify(expected ?? null)) throw new Error(`${name} detail value/formula changed: ${field.name}`);
      }
    }
    audit.quotation_layout[name] = { start_column: layout.startColumn,
      public_rows: Object.fromEntries(layout.publicRows),
      blocks: layout.blocks.map(({ index, headerRow, fields }) => ({index, header_row: headerRow,
        fields: fields.map(({name,row,last,address,sourceAddress}) => ({name,row,last,address,source_address:sourceAddress}))})) };
  }

  const costSheet = attachRangeApi(candidateWorkbook.getWorksheet("成本明细"));
  if (!costSheet) throw new Error("saved workbook is missing sheet: 成本明细");
  if (rangePlainValues(costSheet, `A${costDetailLastRow}`)[0][0] !== "合计") {
    throw new Error("saved workbook cost-detail subtotal is missing");
  }
  const formulaOrderTotal = items.reduce(
    (sum, item) => sum + formulaOrderLineBreakdown(item).lineTotal, 0,
  );
  assertClose(
    rangePlainValues(costSheet, `M${costDetailLastRow}`)[0][0],
    formulaOrderTotal,
    "cost-detail order total",
  );
  audit["成本明细"] = rangePlainValues(costSheet, `A1:O${costDetailLastRow}`);

  const formulaErrors = scanWorkbookFormulaErrors(candidateWorkbook);
  if (formulaErrors.length) {
    throw new Error(`formal quotation contains formula errors: ${formulaErrors.join(", ")}`);
  }
  audit.formula_errors = [];
  return audit;
};

// Verify before serialization, then verify the serialized temporary file again
// before publishing it to the user-selected path.
addAttachmentSnapshotSheet(workbook,payload);
verifyWorkbookContents(workbook);
// Generate beside the destination first and publish only after the workbook
// is complete. A crash can no longer leave a zero-byte or half-written final
// quotation in the user's folder.
const resolvedOutputPath = path.resolve(outputPath);
await fs.mkdir(path.dirname(resolvedOutputPath), { recursive: true });
const temporaryOutputPath = `${resolvedOutputPath}.tmp-${process.pid}-${Date.now()}.xlsx`;
try {
  await workbook.xlsx.writeFile(temporaryOutputPath);
  const stat = await fs.stat(temporaryOutputPath);
  if (!stat.isFile() || stat.size === 0) throw new Error("导出组件生成了空文件");
  assertNoWorkbookAnnotations(await fs.readFile(temporaryOutputPath));
  const serializedWorkbook = new ExcelJS.Workbook();
  await serializedWorkbook.xlsx.readFile(temporaryOutputPath);
  const serializedAudit = verifyWorkbookContents(serializedWorkbook);
  if (process.env.QUOTE_EXPORT_QA_DIR) {
    await fs.mkdir(process.env.QUOTE_EXPORT_QA_DIR, { recursive: true });
    await fs.writeFile(
      path.join(process.env.QUOTE_EXPORT_QA_DIR, "workbook-audit.json"),
      JSON.stringify(serializedAudit, null, 2),
      "utf8",
    );
  }
  await fs.copyFile(temporaryOutputPath, resolvedOutputPath);
  const finalStat = await fs.stat(resolvedOutputPath);
  if (!finalStat.isFile() || finalStat.size !== stat.size) {
    throw new Error("正式报价单落盘校验失败");
  }
} finally {
  await fs.rm(temporaryOutputPath, { force: true });
}
console.log(`exported ${resolvedOutputPath}`);
