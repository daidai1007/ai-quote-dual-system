// Billing rules for attachments that are quick-quote only.
// This configuration-change item is intentionally excluded from the
// formula quotation while remaining part of the quick quotation.

export const QUICK_ONLY_ATTACHMENT_PRICES = Object.freeze({
  JSJP单门改为上下门: 150,
});

function normalizeName(value) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, "")
    .replace(/[，、,;；:：/\\|（）()【】\[\]_-]/g, "")
    .replace(/单开门/g, "单门")
    .replace(/双开门/g, "双门");
}

const NAME_KEYS = ["attachment_name", "name", "item_name", "display_name", "label", "名称"];
const QUANTITY_KEYS = ["quantity", "qty", "selected_quantity", "数量"];
const PRICE_KEYS = ["unit_price_override", "unit_price", "price", "selected_unit_price", "单价"];

function firstValue(item, keys) {
  for (const key of keys) {
    if (item && item[key] !== undefined && item[key] !== null && item[key] !== "") return item[key];
  }
  return undefined;
}

function numeric(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function quickOnlyPriceFor(item) {
  const name = typeof item === "string" ? item : firstValue(item, NAME_KEYS);
  const key = normalizeName(name);
  if (Object.prototype.hasOwnProperty.call(QUICK_ONLY_ATTACHMENT_PRICES, key)) {
    return QUICK_ONLY_ATTACHMENT_PRICES[key];
  }
  return 0;
}

function quickOnlyUnitPriceFor(item) {
  const defaultPrice = quickOnlyPriceFor(item);
  if (defaultPrice <= 0 || typeof item === "string") return defaultPrice;
  const override = firstValue(item, PRICE_KEYS);
  return override === undefined ? defaultPrice : Math.max(0, numeric(override, defaultPrice));
}

export function isQuickOnlyAttachment(item) {
  return quickOnlyPriceFor(item) > 0;
}

export function calculateQuickOnlyAttachmentFee(selectedAttachments = []) {
  const items = Array.isArray(selectedAttachments) ? selectedAttachments : [];
  return Number(items.reduce((sum, item) => {
    const quantity = typeof item === "string" ? 1 : numeric(firstValue(item, QUANTITY_KEYS), 1);
    return sum + quickOnlyUnitPriceFor(item) * Math.max(0, quantity);
  }, 0).toFixed(6));
}

function subtract(value, fee) {
  const number = numeric(value, 0);
  return Number(Math.max(0, number - fee).toFixed(6));
}

function clone(value) {
  if (Array.isArray(value)) return value.map(clone);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, clone(child)]));
  }
  return value;
}

/**
 * Adjust a dual-quote result so the configuration-change attachment is
 * billed only in quick quote. The operation is idempotent.
 */
export function applyQuickOnlyAttachmentRuleToQuoteRow(row, selectedAttachments = []) {
  const result = clone(row ?? {});
  const fee = calculateQuickOnlyAttachmentFee(selectedAttachments);
  const alreadyApplied = Number(result?.attachment_billing_rules?.quick_only_attachment_fee ?? 0);
  if (fee <= 0 || alreadyApplied === fee) return result;

  if (result.formula_attachment_fee !== undefined) result.formula_attachment_fee = subtract(result.formula_attachment_fee, fee);
  if (result.formula_attachment_cost !== undefined) result.formula_attachment_cost = subtract(result.formula_attachment_cost, fee);
  if (result.formula_total_cost !== undefined) result.formula_total_cost = subtract(result.formula_total_cost, fee);

  for (const key of ["formula_cost", "formula_quote"]) {
    const nested = result[key];
    if (!nested || typeof nested !== "object") continue;
    if (nested.attachment_fee !== undefined) nested.attachment_fee = subtract(nested.attachment_fee, fee);
    if (nested.attachment_cost !== undefined) nested.attachment_cost = subtract(nested.attachment_cost, fee);
    if (nested.total_cost !== undefined) nested.total_cost = subtract(nested.total_cost, fee);
  }

  result.attachment_billing_rules = {
    ...(result.attachment_billing_rules ?? {}),
    version: "quick-only-config-v2",
    quick_only_attachment_fee: fee,
    formula_excluded: true,
  };
  return result;
}

export function splitAttachmentFees(selectedAttachments = []) {
  const items = Array.isArray(selectedAttachments) ? selectedAttachments : [];
  const quickOnly = calculateQuickOnlyAttachmentFee(items);
  const all = items.reduce((sum, item) => {
    const quantity = typeof item === "string" ? 1 : numeric(firstValue(item, QUANTITY_KEYS), 1);
    const explicit = typeof item === "string" ? 0 : numeric(firstValue(item, PRICE_KEYS), 0);
    return sum + Math.max(0, quantity) * (quickOnlyUnitPriceFor(item) || explicit);
  }, 0);
  return { formulaFee: Number(Math.max(0, all - quickOnly).toFixed(6)), quickOnlyFee: quickOnly, quickFee: Number(all.toFixed(6)) };
}
