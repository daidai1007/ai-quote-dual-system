const hasFiniteNumber = (value) => value !== null && value !== undefined && value !== ""
  && Number.isFinite(Number(value));
const asFiniteNumber = (value, fallback = 0) =>
  hasFiniteNumber(value) ? Number(value) : fallback;

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

/** Return the approved quick-quote discount category, or null. */
export function quickDiscountCategory(item = {}) {
  const candidates = categoryCandidates(item);
  const combined = candidates.join(" ");
  if (combined.includes("安装板单发")) return null;
  if (/JK\s*安装板/i.test(combined)) return "JK安装板";
  for (const category of ["通风顶罩", "防雨顶", "分段板", "玻璃门", "内门", "底座", "侧板"]) {
    if (combined.includes(category)) return category;
  }
  if (combined.includes("安装板") || combined.includes("填充板")) return "安装板";
  return null;
}

/** Attachments that remain at original price in both quotation methods. */
export function attachmentExcludedFromDiscount(item = {}) {
  return categoryCandidates(item).some((value) => value === "门安装条");
}

export function quickAttachmentLineAmount(item = {}) {
  const sign = Number(item.attachment_price_sign) === -1 ? -1 : 1;
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (hasFiniteNumber(item[key])) {
      return Math.abs(Number(item[key])) * sign;
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
  return Math.abs(unitPrice) * quantity * sign;
}

export function attachmentUsesCabinetQuantity(item = {}) {
  const combined = categoryCandidates(item).join(" ");
  if (combined.includes("风机") || combined.includes("滤网")) return false;
  return !ATTACHMENT_QUANTITY_EXEMPT_CATEGORIES.some((category) => combined.includes(category));
}

export function effectiveAttachmentQuantity(
  item = {}, cabinetQuantity = 1, gangedCabinetCount = 1,
) {
  const selected = asFiniteNumber(item.quantity, 1);
  const cabinets = asFiniteNumber(cabinetQuantity, 1);
  const splitCount = asFiniteNumber(gangedCabinetCount, 1);
  // In a ganged quote the stored quantity already describes one complete
  // ganged set. Automatic limiter/reinforcement rows contain the sum required
  // by all child cabinets, and fixed bases already exist as one row per child.
  if (splitCount > 1) return selected * cabinets;
  if (!attachmentUsesCabinetQuantity(item)) return selected;
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

/**
 * Compute the selective quick-quote discount without changing stored prices.
 * The database quick total remains authoritative; attachment rows determine
 * which part of that total is eligible for the selected factor.
 */
export function quickDiscountBreakdown({ quote = {}, attachments = [], discount = 1 } = {}) {
  const rawTotal = asFiniteNumber(quote.total_cost);
  const listedAttachmentTotal = attachments.reduce(
    (sum, item) => sum + quickAttachmentLineAmount(item),
    0,
  );
  const attachmentFee = hasFiniteNumber(quote.attachment_fee)
    ? Number(quote.attachment_fee)
    : listedAttachmentTotal;
  const basePrice = hasFiniteNumber(quote.base_price)
    ? Number(quote.base_price)
    : rawTotal - attachmentFee;
  const listedEligible = attachments.reduce(
    (sum, item) => sum + (quickDiscountCategory(item) ? quickAttachmentLineAmount(item) : 0),
    0,
  );
  const eligibleAttachmentTotal = listedEligible;
  const originalPriceAttachmentTotal = attachmentFee - eligibleAttachmentTotal;
  const factor = hasFiniteNumber(discount) ? Number(discount) : 1;
  const discountedTotal = (basePrice + eligibleAttachmentTotal) * factor
    + originalPriceAttachmentTotal;
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
  gangedCabinetCount = 1, freightFee = 0,
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
  const unlistedDifference = unit.attachmentFee - unit.listedAttachmentTotal;
  const originalPriceAttachmentTotal = listedOriginalTotal
    + unlistedDifference * cabinets;
  const factor = asFiniteNumber(discount, 1);
  const unitFreight = Math.max(0, asFiniteNumber(freightFee, 0));
  const freightTotal = unitFreight * cabinets;
  const lineTotal = (unit.basePrice * cabinets + eligibleAttachmentTotal) * factor
    + originalPriceAttachmentTotal + freightTotal;
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
    equivalentUnitTotal: cabinets ? lineTotal / cabinets : lineTotal,
  };
}
