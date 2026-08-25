const asFiniteNumber = (value, fallback = 0) =>
  Number.isFinite(Number(value)) ? Number(value) : fallback;

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

export function quickAttachmentLineAmount(item = {}) {
  for (const key of ["total_price", "total_cost", "amount", "subtotal"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      return Number(item[key]);
    }
  }
  let unitPrice = 0;
  for (const key of ["unit_price_override", "matched_price", "unit_price", "price"]) {
    if (item[key] !== null && item[key] !== undefined && Number.isFinite(Number(item[key]))) {
      unitPrice = Number(item[key]);
      break;
    }
  }
  const quantity = asFiniteNumber(item.quantity, 1);
  return unitPrice * quantity;
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
  const attachmentFee = Number.isFinite(Number(quote.attachment_fee))
    ? Number(quote.attachment_fee)
    : listedAttachmentTotal;
  const basePrice = Number.isFinite(Number(quote.base_price))
    ? Number(quote.base_price)
    : rawTotal - attachmentFee;
  const listedEligible = attachments.reduce(
    (sum, item) => sum + (quickDiscountCategory(item) ? quickAttachmentLineAmount(item) : 0),
    0,
  );
  const eligibleAttachmentTotal = listedEligible;
  const originalPriceAttachmentTotal = attachmentFee - eligibleAttachmentTotal;
  const factor = Number.isFinite(Number(discount)) ? Number(discount) : 1;
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
