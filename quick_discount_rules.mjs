const hasFiniteNumber = (value) => value !== null && value !== undefined && value !== ""
  && Number.isFinite(Number(value));
const asFiniteNumber = (value, fallback = 0) =>
  hasFiniteNumber(value) ? Number(value) : fallback;

export const PRICING_BASIS = 'per_unit_set_v1';
export const MANAGEMENT_FEE_RATE = 0.06;
export const MANAGEMENT_FEE_BASIS = 'pre_management_cost_with_freight_v1';
export const MANAGEMENT_COST_KEYS = Object.freeze(['material_cost','auxiliary_cost','labor_cost','attachment_fee','spray_cost']);
export const missingManagementCosts = quote => MANAGEMENT_COST_KEYS.filter(key=>!hasFiniteNumber(quote?.[key]));
// Decimal coefficient + scale, without a dependency or binary half-cent rounding.
const decimal = (value = 0) => {
  const text = String(value == null || value === '' ? 0 : value).trim();
  if (text.length > 128) throw new Error('金额精度超出范围');
  if (!Number.isFinite(Number(text))) throw new Error('金额必须为有效数值');
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text);
  if (!match || !(match[2] || match[3])) throw new Error('金额必须为有效数值');
  let coefficient = BigInt((match[2] || '0') + (match[3] || '')) * (match[1] === '-' ? -1n : 1n);
  let scale = (match[3] || '').length - Number(match[4] || 0);
  if (Math.abs(scale) > 400) throw new Error('金额精度超出范围');
  if (scale < 0) { coefficient *= 10n ** BigInt(-scale); scale = 0; }
  return [coefficient, scale];
};
const roundedCents = (coefficient, scale) => {
  if (scale <= 2) return coefficient * 10n ** BigInt(2 - scale);
  const divisor = 10n ** BigInt(scale - 2);
  const sign = coefficient < 0n ? -1n : 1n;
  const absolute = coefficient * sign;
  return sign * (absolute / divisor + (absolute % divisor * 2n >= divisor ? 1n : 0n));
};
export const money = (value = 0) => Number(roundedCents(...decimal(value))) / 100;
export const moneySum = (values) => Number(Array.from(values).reduce(
  (sum, value) => sum + roundedCents(...decimal(value)), 0n)) / 100;
export const moneyProduct = (...values) => {
  const [coefficient, scale] = values.reduce(([coefficient, scale], value) => {
    const [next, places] = decimal(value);
    return [coefficient * next, scale + places];
  }, [1n, 0]);
  return Number(roundedCents(coefficient, scale)) / 100;
};
// Exact intermediate sum for saved component allocation; no cent rounding yet.
export const decimalSum = values => {
  const parts=Array.from(values,decimal),scale=Math.max(0,...parts.map(p=>p[1]));
  const coefficient=parts.reduce((sum,[value,places])=>sum+value*10n**BigInt(scale-places),0n);
  const text=String(coefficient<0n?-coefficient:coefficient).padStart(scale+1,'0');
  return (coefficient<0n?'-':'')+(scale?text.slice(0,-scale)+'.'+text.slice(-scale):text);
};

// Formula totals exclude freight itself, but freight participates in the fee.
// Old management/total snapshots are derived data, never pricing inputs.
export function applyManagementFee(quote = {}, freightFee = 0) {
  const result={...quote,management_fee_rate:MANAGEMENT_FEE_RATE,management_fee_basis:MANAGEMENT_FEE_BASIS};
  const base=missingManagementCosts(quote).length?null:moneySum(MANAGEMENT_COST_KEYS.map(key=>quote[key]));
  if(base===null) return {...result,management_fee_base:null,management_fee:null,total_cost:null};
  result.management_fee_base=moneySum([base,Math.max(0,asFiniteNumber(freightFee))]);
  result.management_fee=moneyProduct(result.management_fee_base,MANAGEMENT_FEE_RATE);
  result.total_cost=moneySum([base,result.management_fee]);
  return result;
}

export const QUICK_DISCOUNT_ATTACHMENT_CATEGORIES = Object.freeze([
  "底座",
  "侧板",
  "安装板",
  "内门",
  "玻璃门",
  "通风顶罩",
  "防雨顶",
  "分段板",
  "JK安装板",
  "无孔承板",
  "有孔承板",
]);
export const ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES = Object.freeze([
  "侧板", "门变形", "风机滤网",
]);
export const GANGED_FIXED_BASE_MATCH_KEY = "ganged_fixed_base_match";

const categoryCandidates = (item = {}) => [
  item.category_level3,
  item.category_level2,
  item.category_level1,
  item.attachment_category,
  item.category,
  item.item_name,
  item.model_code,
].map((value) => String(value || "").trim()).filter(Boolean);

const topLevelCategory = (item = {}) => [
  item.category_level1,
  item.attachment_category,
  item.category,
].map((value) => String(value || "").trim()).find(Boolean) || "";

/** Return the approved quick-quote discount category, or null. */
export function quickDiscountCategory(item = {}) {
  if (topLevelCategory(item) === "其他附件") return null;
  const candidates = categoryCandidates(item);
  const combined = candidates.join(" ");
  if (candidates.includes("填充安装板")) return null;
  if (combined.includes("安装板单发")) return null;
  if (/JK\s*安装板/i.test(combined)) return "JK安装板";
  for (const category of [
    "无孔承板", "有孔承板", "通风顶罩", "防雨顶", "分段板",
    "玻璃门", "内门", "底座", "侧板",
  ]) {
    if (combined.includes(category)) return category;
  }
  if (combined.includes("安装板") || combined.includes("填充板")) return "安装板";
  return null;
}

/** Attachments that remain at original price in both quotation methods. */
export function attachmentExcludedFromDiscount(item = {}) {
  if (topLevelCategory(item) === "其他附件") return true;
  return categoryCandidates(item).some((value) => value === "门安装条" || value === "填充安装板");
}

/** Attachments omitted only from formula quotations. */
export function formulaAttachmentExcluded(item = {}) {
  if(item.catalog_version) return item.status === 'QUICK_ONLY';
  // 门变形 is a closed first-level database catalogue. Keep this exact so an
  // unrelated attachment whose name merely contains the words is not omitted.
  return topLevelCategory(item) === "门变形";
}

export function quickAttachmentLineAmount(item = {}) {
  if (item.pending_manual_dimensions?.length) return 0;
  const edited = item.custom_amount_edited === true || (!Object.hasOwn(item, 'custom_amount_edited')
    && item.quick_amount_override != null && Number(item.quick_amount_override) !== 0);
  if (edited && hasFiniteNumber(item.quick_amount_override)) return money(item.quick_amount_override);
  if (hasFiniteNumber(item.quick_amount)) return money(item.quick_amount);
  const sign = Number(item.attachment_price_sign) === -1 ? -1 : 1;
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (hasFiniteNumber(item[key])) {
      return moneyProduct(Math.abs(Number(item[key])), sign);
    }
  }
  let unitPrice = 0;
  for (const key of ["unit_price_override", "matched_price", "unit_price", "price"]) {
    if (hasFiniteNumber(item[key])) {
      unitPrice = Number(item[key]);
      break;
    }
  }
  const quantity = asFiniteNumber(item.quantity, 1);
  return moneyProduct(Math.abs(unitPrice), quantity, sign);
}

export function attachmentUsesCabinetQuantity(item = {}) {
  const combined = categoryCandidates(item).join(" ");
  if (combined.includes("风机") || combined.includes("滤网")) return false;
  return !ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES.some((category) => combined.includes(category));
}

function manuallyQuantifiedAttachment(item = {}) {
  const source = String(item.selection_source || "").trim().toLowerCase();
  return Boolean(
    item.cost_quantity_manual || item.custom
    || source === "manual" || source === "quote_local"
  );
}

export function effectiveAttachmentQuantity(
  item = {}, cabinetQuantity = 1, gangedCabinetCount = 1,
) {
  const selected = asFiniteNumber(item.quantity, 1);
  const cabinets = asFiniteNumber(cabinetQuantity, 1);
  // The attachment editor already contains the entire ganged set, including manual rows.
  // Attachment rows stored on a quote are per-cabinet values.  Scale every
  // ordinary row by the order quantity; exempting fans/side panels/door
  // transformations made identical cabinet lines with quantities 1 and 10
  // produce different unit prices.  Ganged child rows are already expanded
  // by child index and still use the complete-set branch above.
  return selected * cabinets;
}

export function effectiveAttachmentLineAmount(
  item = {}, cabinetQuantity = 1, gangedCabinetCount = 1,
) {
  const selected = asFiniteNumber(item.quantity, 1);
  const lineAmount = quickAttachmentLineAmount(item);
  if (selected === 0) return 0;
  return lineAmount * effectiveAttachmentQuantity(
    item, cabinetQuantity, gangedCabinetCount,
  ) / selected;
}

export function formulaAttachmentLineAmount(item = {}) {
  if(item.formula_cost_edited===true && !['ERROR','PENDING_MANUAL'].includes(item.status))
    return moneyProduct(item.formula_unit_cost_override,item.quantity??1,item.attachment_price_sign??1);
  if(item.custom===true) {
    if(item.formula_amount==null||!Number.isFinite(Number(item.formula_amount)))
      throw new Error('人工新增附件公式成本未完成，不能汇总');
    return Number(item.formula_amount);
  }
  if(!item.catalog_version) {
    if(item.formula_amount!=null && Number.isFinite(Number(item.formula_amount)))
      return Number(item.formula_amount);
    return quickAttachmentLineAmount(item);
  }
  if(item.status==='QUICK_ONLY') return 0;
  if(item.status==='ERROR'||item.formula_amount==null) throw new Error('附件公式成本未完成，不能汇总');
  return Number(item.formula_amount);
}
export function effectiveFormulaAttachmentLineAmount(item={},cabinetQuantity=1,gangedCabinetCount=1) {
  return formulaAttachmentLineAmount(item)*effectiveAttachmentQuantity(item,cabinetQuantity,gangedCabinetCount)/Number(item.quantity||1);
}

/**
 * Compute the selective quick-quote discount without changing stored prices.
 * The cabinet base comes from the quote; current per-set attachment rows
 * provide the only attachment total and its eligible/original-price split.
 */
export function quickDiscountBreakdown({ quote = {}, attachments = [], discount = 1 } = {}) {
  const rawTotal = money(quote.total_cost);
  const listedAttachmentTotal = moneySum(attachments.map(quickAttachmentLineAmount));
  // The attachment editor is the source of truth for the current draft.
  // Keep the API fee only long enough to recover the cabinet base when an
  // old snapshot still contains a different aggregate attachment fee.
  const storedAttachmentFee = hasFiniteNumber(quote.attachment_fee)
    ? Number(quote.attachment_fee)
    : listedAttachmentTotal;
  const attachmentFee = listedAttachmentTotal;
  const basePrice = money(hasFiniteNumber(quote.base_price)
    ? Number(quote.base_price)
    : rawTotal - storedAttachmentFee);
  const listedEligible = moneySum(attachments.filter(quickDiscountCategory).map(quickAttachmentLineAmount));
  const eligibleAttachmentTotal = listedEligible;
  const originalPriceAttachmentTotal = moneySum([attachmentFee, -eligibleAttachmentTotal]);
  const factor = hasFiniteNumber(discount) ? Number(discount) : 1;
  const discountedTotal = moneySum([moneyProduct(moneySum([basePrice, eligibleAttachmentTotal]), factor),
    originalPriceAttachmentTotal]);
  return {
    rawTotal,
    basePrice,
    attachmentFee,
    listedAttachmentTotal,
    eligibleAttachmentTotal,
    originalPriceAttachmentTotal,
    discount: factor,
    discountedTotal,
  };
}

/** Compute one complete quote-line total with attachment quantity exceptions. */
export function quickOrderLineBreakdown({
  quote = {}, attachments = [], discount = 1, cabinetQuantity = 1,
  gangedCabinetCount = 1, freightFee = 0, materialDifference = 0,
} = {}) {
  const unit = quickDiscountBreakdown({ quote, attachments, discount });
  const cabinets = asFiniteNumber(cabinetQuantity, 1);
  const splitCount = asFiniteNumber(gangedCabinetCount, 1);
  const eligibleAttachmentTotal = attachments.reduce(
    (sum, item) => sum + (quickDiscountCategory(item)
      ? effectiveAttachmentLineAmount(item, cabinets, splitCount) : 0),
    0,
  );
  const listedOriginalTotal = attachments.reduce(
    (sum, item) => sum + (quickDiscountCategory(item)
      ? 0 : effectiveAttachmentLineAmount(item, cabinets, splitCount)),
    0,
  );
  // There is no second, hidden attachment bucket: all current attachment
  // money comes from the rows displayed in the editor.
  const unlistedDifference = 0;
  const originalPriceAttachmentTotal = listedOriginalTotal
    + unlistedDifference * cabinets;
  const factor = asFiniteNumber(discount, 1);
  const unitFreight = money(Math.max(0, asFiniteNumber(freightFee, 0)));
  const freightTotal = moneyProduct(unitFreight, cabinets);
  const unitTotal = moneySum([unit.discountedTotal, unitFreight, materialDifference]);
  const lineTotal = moneyProduct(unitTotal, cabinets);
  return {
    ...unit,
    cabinetQuantity: cabinets,
    gangedCabinetCount: splitCount,
    eligibleAttachmentTotal,
    originalPriceAttachmentTotal,
    unlistedDifference,
    freightFee: unitFreight,
    freightTotal,
    lineTotal,
    equivalentUnitTotal: unitTotal,
  };
}

/** Check the frozen customer-facing values against the canonical quote, not the screen formatter. */
export function validateQuoteDisplay(item) {
  if (item.pricing_basis == null) return; // Historical payloads keep their original contract.
  if (item.pricing_basis !== PRICING_BASIS) throw new Error('不支持的报价金额口径，请更新客户端');
  const display = item.quote_display;
  if (!display || typeof display !== 'object' || Array.isArray(display)) throw new Error('缺少已确认的报价显示快照');
  const quantity = Number(item.quantity);
  if (!Number.isSafeInteger(quantity) || quantity < 1 || Number(display.quantity) !== quantity)
    throw new Error('报价显示快照的成批产品数量不一致');
  if (!hasFiniteNumber(display.discount) || Number(display.discount) !== Number(item.quick_discount ?? 1))
    throw new Error('报价显示快照的折扣系数不一致');
  const materialDifference = materialDifferenceAmount(item);
  const line = quickOrderLineBreakdown({quote: item.quick, attachments: item.attachments,
    discount: item.quick_discount ?? 1, cabinetQuantity: quantity,
    freightFee: item.freight_fee ?? item.freight ?? 0, materialDifference});
  for (const [field, expected] of Object.entries({unit_price: line.equivalentUnitTotal,
    total: line.lineTotal, attachment_face_price: line.attachmentFee,
    material_difference: materialDifference, quick_base_price: line.basePrice,
    quick_attachment_fee: line.attachmentFee, quick_total_cost: moneySum([line.basePrice, line.attachmentFee])})) {
    if (!hasFiniteNumber(display[field]) || money(display[field]) !== Number(display[field])
        || money(display[field]) !== money(expected))
      throw new Error(`报价金额不一致（${field}）：显示 ${display[field]}，计算 ${expected}，请重新确认`);
  }
}

export function materialDifferenceAmount(item = {}) {
  if (String(item.material_code || '').trim().toUpperCase() !== 'SUS316') return 0;
  const formula = item.formula || {};
  const groups = formula.material_details?.length ? formula.material_details : (formula.cabinet_material_part_details || []);
  const sgcc = groups.filter(row => String(row.material_code || '').trim().toUpperCase() === 'SGCC')
    .reduce((sum, row) => sum + Math.max(0, asFiniteNumber(row.billable_weight_kg)), 0);
  return moneyProduct(Math.max(0, asFiniteNumber(formula.corrected_material_weight_kg) - sgcc),
    Math.max(0, asFiniteNumber(item.scheme2_cost_settings?.material_difference, 25)));
}
