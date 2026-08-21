// Door-count business rules shared by the dual-quote API response layer.
// Product availability remains database-driven; this module only validates
// the operator's two door counts and applies the approved quick-price delta.

export const VALID_DOOR_COMBINATIONS = Object.freeze([
  Object.freeze([1, 0]),
  Object.freeze([0, 1]),
  Object.freeze([0, 2]),
  Object.freeze([2, 0]),
  Object.freeze([1, 1]),
]);

const VALID_DOOR_KEYS = new Set(VALID_DOOR_COMBINATIONS.map(([single, double]) => `${single}/${double}`));

const integerCount = (value, name) => {
  const count = Number(value);
  if (!Number.isInteger(count) || count < 0) throw new Error(`${name} must be a non-negative integer`);
  return count;
};

export function doorCountsFromInput(input = {}, { allowMissing = true, allowZeroPair = false } = {}) {
  const hasSingle = input.single_door_count !== undefined && input.single_door_count !== null && input.single_door_count !== '';
  const hasDouble = input.double_door_count !== undefined && input.double_door_count !== null && input.double_door_count !== '';
  if (!hasSingle && !hasDouble && allowMissing) return null;
  if (!hasSingle || !hasDouble) throw new Error('single_door_count and double_door_count must be provided together');

  const single = integerCount(input.single_door_count, 'single_door_count');
  const double = integerCount(input.double_door_count, 'double_door_count');
  // Non-door products in the existing desktop client send 0/0 while their
  // two selectors are disabled. Keep that transport value as a no-op.
  if (allowZeroPair && single === 0 && double === 0) return { single, double };
  if (!VALID_DOOR_KEYS.has(`${single}/${double}`)) {
    throw new Error(`door combination must be one of 1/0, 0/1, 0/2, 2/0 or 1/1; received ${single}/${double}`);
  }
  return { single, double };
}

export function databaseVariantForDoorCounts(counts) {
  if (!counts) return null;
  // The mixed 1/1 configuration intentionally uses the single-door product
  // dataset, matching the desktop client's existing selection priority.
  return counts.single > 0 ? 'SINGLE' : 'DOUBLE';
}

export function normalizeDoorVariantInput(input = {}) {
  const counts = doorCountsFromInput(input, { allowZeroPair: true });
  if (!counts) return input;
  if (counts.single === 0 && counts.double === 0) return input;
  const currentProduct = String(input.product_code || '').trim();
  const currentVariant = String(input.variant_code || '').trim().toUpperCase();
  if (currentVariant === 'WIDE' || /_WIDE(?:_EXP)?$/i.test(currentProduct)) return input;

  const variant = databaseVariantForDoorCounts(counts);
  const productCode = /_(?:SINGLE|DOUBLE)$/i.test(currentProduct)
    ? currentProduct.replace(/_(?:SINGLE|DOUBLE)$/i, `_${variant}`)
    : currentProduct;
  return {
    ...input,
    product_code: productCode,
    variant_code: variant,
    single_door_count: counts.single,
    double_door_count: counts.double,
  };
}

const productFamily = (productCode) => String(productCode || '')
  .trim()
  .toUpperCase()
  .replace(/_(?:SINGLE|DOUBLE)$/i, '');

export function quickDoorVariantSurcharge(input = {}) {
  const counts = doorCountsFromInput(input, { allowZeroPair: true });
  if (!counts) return 0;
  if (counts.single === 0 && counts.double === 0) return 0;
  const family = productFamily(input.product_code);
  const key = `${counts.single}/${counts.double}`;
  if (key === '0/1') {
    if (family === 'JS' || family === 'JP') return 150;
    if (family === 'JA' || family === 'JE') return 60;
  }
  if (key === '2/0' && (family === 'JS' || family === 'JP')) return 150;
  if (key === '0/2' && (family === 'JS' || family === 'JP')) return 270;
  return 0;
}

const numberOrNull = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const rounded = (value) => Number(Number(value).toFixed(6));

const clone = (value) => {
  if (Array.isArray(value)) return value.map(clone);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, clone(child)]));
  }
  return value;
};

export function applyDoorVariantQuickPrice(row, input = {}) {
  const result = clone(row ?? {});
  const surcharge = quickDoorVariantSurcharge(input);
  if (surcharge <= 0) return result;

  const counts = doorCountsFromInput(input, { allowMissing: false });
  const existingRule = result.door_variant_billing_rule;
  if (existingRule?.version === 'door-count-quick-v1'
      && Number(existingRule.quick_price_surcharge) === surcharge
      && Number(existingRule.single_door_count) === counts.single
      && Number(existingRule.double_door_count) === counts.double) return result;

  const quick = result.quick_quote;
  if (!quick || typeof quick !== 'object') return result;
  const basePrice = numberOrNull(quick.base_price);
  const totalCost = numberOrNull(quick.total_cost);
  if (basePrice === null || totalCost === null) return result;

  // Older clients may still send the legacy quick-only transformation row.
  // Move its overlapping amount out of attachment_fee before applying the
  // automatic door surcharge so the final price is never charged twice.
  const legacyFee = Math.max(0, numberOrNull(result.attachment_billing_rules?.quick_only_attachment_fee) || 0);
  const migratedLegacyFee = Math.min(legacyFee, surcharge);
  const attachmentFee = numberOrNull(quick.attachment_fee);
  quick.base_price = rounded(basePrice + surcharge);
  quick.total_cost = rounded(totalCost - migratedLegacyFee + surcharge);
  if (attachmentFee !== null && migratedLegacyFee > 0) {
    quick.attachment_fee = rounded(Math.max(0, attachmentFee - migratedLegacyFee));
  }

  result.door_variant_billing_rule = {
    version: 'door-count-quick-v1',
    product_family: productFamily(input.product_code),
    single_door_count: counts.single,
    double_door_count: counts.double,
    quick_price_surcharge: surcharge,
    migrated_legacy_attachment_fee: migratedLegacyFee,
    formula_unchanged: true,
  };
  return result;
}
