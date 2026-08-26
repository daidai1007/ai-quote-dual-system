import assert from 'node:assert/strict';
import test from 'node:test';

import {
  VALID_DOOR_COMBINATIONS,
  applyDoorVariantQuickPrice,
  databaseVariantForDoorCounts,
  doorCountsFromInput,
  normalizeDoorVariantInput,
  quickDoorVariantForCounts,
  quickDoorVariantSurcharge,
} from './door_variant_rules.mjs';

test('door selectors expose exactly the five approved combinations', () => {
  assert.deepEqual(VALID_DOOR_COMBINATIONS, [[1, 0], [0, 1], [0, 2], [2, 0], [1, 1]]);
  for (const [single, double] of VALID_DOOR_COMBINATIONS) {
    assert.deepEqual(doorCountsFromInput({ single_door_count: single, double_door_count: double }), { single, double });
  }
  assert.throws(
    () => doorCountsFromInput({ single_door_count: 2, double_door_count: 1 }),
    /must be one of/,
  );
});

test('0/0 remains a no-op for existing products without door selectors', () => {
  const input = { product_code: 'JM', variant_code: 'DEFAULT', single_door_count: 0, double_door_count: 0 };
  assert.deepEqual(normalizeDoorVariantInput(input), input);
  assert.equal(quickDoorVariantSurcharge(input), 0);
});

test('door counts choose the database product variant', () => {
  assert.equal(databaseVariantForDoorCounts({ single: 1, double: 0 }), 'SINGLE');
  assert.equal(databaseVariantForDoorCounts({ single: 0, double: 1 }), 'DOUBLE');
  assert.equal(databaseVariantForDoorCounts({ single: 1, double: 1 }), 'SINGLE');
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'JS_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 1 }),
    { product_code: 'JS_DOUBLE', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 1 },
  );
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'JP_DOUBLE', variant_code: 'DOUBLE', single_door_count: 1, double_door_count: 0 }),
    { product_code: 'JP_SINGLE', variant_code: 'SINGLE', single_door_count: 1, double_door_count: 0 },
  );
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'JA_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 2 }),
    { product_code: 'JA_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 2 },
    'JA must use its one formula template with door control cells',
  );
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'XX_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 1 }),
    { product_code: 'XX_DOUBLE', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 1 },
  );
  assert.throws(
    () => normalizeDoorVariantInput({ product_code: 'XX_SINGLE', single_door_count: 1, double_door_count: 1 }),
    /must be 1\/0 or 0\/1/,
  );
});

test('quick quote classifies the five combinations as single or double', () => {
  assert.equal(quickDoorVariantForCounts({ single: 1, double: 0 }), 'SINGLE');
  assert.equal(quickDoorVariantForCounts({ single: 0, double: 1 }), 'DOUBLE');
  assert.equal(quickDoorVariantForCounts({ single: 0, double: 2 }), 'DOUBLE');
  assert.equal(quickDoorVariantForCounts({ single: 2, double: 0 }), 'SINGLE');
  assert.equal(quickDoorVariantForCounts({ single: 1, double: 1 }), 'SINGLE');
});

test('quick-price door surcharge follows the approved product matrix', () => {
  const fee = (product_code, single_door_count, double_door_count) => quickDoorVariantSurcharge({
    product_code, single_door_count, double_door_count,
  });
  assert.equal(fee('JS_DOUBLE', 0, 1), 0);
  assert.equal(fee('JP_DOUBLE', 0, 1), 0);
  assert.equal(fee('JA_SINGLE', 0, 1), 0);
  assert.equal(fee('JE_DOUBLE', 0, 1), 0);
  assert.equal(fee('JS_SINGLE', 2, 0), 150);
  assert.equal(fee('JP_SINGLE', 2, 0), 150);
  assert.equal(fee('JS_DOUBLE', 0, 2), 270);
  assert.equal(fee('JP_SINGLE', 0, 2), 270);
  assert.equal(fee('JS_SINGLE', 1, 1), 270);
  assert.equal(fee('JP_SINGLE', 1, 1), 270);
  assert.equal(fee('JA_SINGLE', 2, 0), 0);
  assert.equal(fee('JA_SINGLE', 0, 2), 0);
  assert.equal(fee('JA_SINGLE', 1, 1), 0);
  assert.equal(fee('JE_DOUBLE', 0, 2), 0);
  assert.equal(fee('JE_SINGLE', 1, 1), 0);
  assert.equal(fee('JS_SINGLE', 1, 0), 0);
});

test('automatic door surcharge changes quick base and total only and is idempotent', () => {
  const row = {
    formula_cost: { total_cost: 888, material_cost: 200 },
    quick_quote: { base_price: 1000, attachment_fee: 20, total_cost: 1020 },
  };
  const input = { product_code: 'JP_DOUBLE', single_door_count: 0, double_door_count: 2 };
  const adjusted = applyDoorVariantQuickPrice(row, input);
  assert.deepEqual(adjusted.formula_cost, row.formula_cost);
  assert.equal(adjusted.quick_quote.base_price, 1270);
  assert.equal(adjusted.quick_quote.attachment_fee, 20);
  assert.equal(adjusted.quick_quote.total_cost, 1290);
  assert.equal(adjusted.quick_quote.door_variant, 'DOUBLE');
  assert.deepEqual(applyDoorVariantQuickPrice(adjusted, input), adjusted);
  assert.equal(row.quick_quote.base_price, 1000, 'input row must not be mutated');
});

test('legacy JS/JP quick-only attachment fee is not charged twice', () => {
  const row = {
    formula_cost: { total_cost: 700 },
    quick_quote: { base_price: 1000, attachment_fee: 150, total_cost: 1150 },
    attachment_billing_rules: { quick_only_attachment_fee: 150 },
  };
  const adjusted = applyDoorVariantQuickPrice(row, {
    product_code: 'JS_SINGLE', single_door_count: 2, double_door_count: 0,
  });
  assert.equal(adjusted.formula_cost.total_cost, 700);
  assert.equal(adjusted.quick_quote.base_price, 1150);
  assert.equal(adjusted.quick_quote.attachment_fee, 0);
  assert.equal(adjusted.quick_quote.total_cost, 1150);
  assert.equal(adjusted.door_variant_billing_rule.migrated_legacy_attachment_fee, 150);
});

test('zero-surcharge combinations still expose their quick single/double class', () => {
  const adjusted = applyDoorVariantQuickPrice({
    formula_cost: { total_cost: 700 },
    quick_quote: { base_price: 1000, attachment_fee: 0, total_cost: 1000 },
  }, { product_code: 'JE_SINGLE', single_door_count: 1, double_door_count: 1 });
  assert.equal(adjusted.quick_quote.door_variant, 'SINGLE');
  assert.equal(adjusted.door_variant_billing_rule.quick_price_surcharge, 0);
  assert.equal(adjusted.formula_cost.total_cost, 700);
});
