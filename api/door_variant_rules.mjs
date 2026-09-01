// Door-count business rules shared by the dual-quote API response layer.
// Product availability remains database-driven; this module only validates
// the operator's two door counts and selects the approved quote source.

export const VALID_DOOR_COMBINATIONS = Object.freeze([
  Object.freeze([1, 0]),
  Object.freeze([0, 1]),
  Object.freeze([0, 2]),
  Object.freeze([2, 0]),
  Object.freeze([1, 1]),
]);

export const FORMULA_MULTI_DOOR_FAMILIES = Object.freeze(['JS', 'JP', 'JA', 'JE']);

const VALID_DOOR_KEYS = new Set(VALID_DOOR_COMBINATIONS.map(([single, double]) => `${single}/${double}`));
const FORMULA_MULTI_DOOR_FAMILY_SET = new Set(FORMULA_MULTI_DOOR_FAMILIES);

const productFamily = (productCode) => String(productCode || '')
  .trim()
  .toUpperCase()
  .replace(/_(?:SINGLE|DOUBLE)$/i, '');

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
  // Keep 0/0 as a backward-compatible no-op for drafts created by clients
  // that predate door selection on every product.
  if (allowZeroPair && single === 0 && double === 0) return { single, double };
  if (!VALID_DOOR_KEYS.has(`${single}/${double}`)) {
    throw new Error(`door combination must be one of 1/0, 0/1, 0/2, 2/0 or 1/1; received ${single}/${double}`);
  }
  return { single, double };
}

export function databaseVariantForDoorCounts(counts) {
  if (!counts) return null;
  return counts.single > 0 ? 'SINGLE' : 'DOUBLE';
}

export function quickDoorVariantForCounts(counts, productCode = '') {
  if (!counts) return null;
  const family = productFamily(productCode);
  // Quick quote reads the SINGLE record for every approved combination in
  // JS/JP/JA/JE.  Door counts remain in the payload for quantity/BOM rules;
  // they do not switch the quick-price source or add an automatic surcharge.
  if (FORMULA_MULTI_DOOR_FAMILY_SET.has(family)) {
    return 'SINGLE';
  }
  return databaseVariantForDoorCounts(counts);
}

export function normalizeDoorVariantInput(input = {}) {
  const counts = doorCountsFromInput(input, { allowZeroPair: true });
  if (!counts) return input;
  if (counts.single === 0 && counts.double === 0) return input;
  const currentProduct = String(input.product_code || '').trim();
  const currentVariant = String(input.variant_code || '').trim().toUpperCase();
  const family = productFamily(currentProduct);
  if (currentVariant === 'WIDE' || /_WIDE(?:_EXP)?$/i.test(currentProduct)) return input;

  // JA has one database formula template. All five JA door combinations are
  // evaluated by its two formula control cells, so never invent JA_DOUBLE.
  if (family === 'JA') {
    return {
      ...input,
      product_code: currentProduct,
      variant_code: currentVariant || 'SINGLE',
      single_door_count: counts.single,
      double_door_count: counts.double,
    };
  }

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

export function normalizeQuickDoorVariantInput(input = {}) {
  const counts = doorCountsFromInput(input, { allowZeroPair: true });
  if (!counts || (counts.single === 0 && counts.double === 0)) return input;
  const currentProduct = String(input.product_code || '').trim();
  const currentVariant = String(input.variant_code || '').trim().toUpperCase();
  const family = productFamily(currentProduct);
  if (currentVariant === 'WIDE' || /_WIDE(?:_EXP)?$/i.test(currentProduct)) return input;
  const variant = quickDoorVariantForCounts(counts, currentProduct);
  const productCode = FORMULA_MULTI_DOOR_FAMILY_SET.has(family)
    ? `${family}_SINGLE`
    : /_(?:SINGLE|DOUBLE)$/i.test(currentProduct)
      ? currentProduct.replace(/_(?:SINGLE|DOUBLE)$/i, `_${variant}`)
      : currentProduct;
  return {
    ...input,
    product_code: productCode,
    variant_code: variant,
    product_family: family,
  };
}
