import assert from 'node:assert/strict';
import test from 'node:test';

import * as doorRules from './door_variant_rules.mjs';

const {
  VALID_DOOR_COMBINATIONS,
  databaseVariantForDoorCounts,
  doorCountsFromInput,
  normalizeDoorVariantInput,
  normalizeQuickDoorVariantInput,
  quickDoorVariantForCounts,
} = doorRules;

test('door selectors expose exactly the five approved combinations', () => {
  assert.deepEqual(VALID_DOOR_COMBINATIONS, [[1, 0], [0, 1], [0, 2], [2, 0], [1, 1]]);
  for (const [single, double] of VALID_DOOR_COMBINATIONS) {
    assert.deepEqual(
      doorCountsFromInput({ single_door_count: single, double_door_count: double }),
      { single, double },
    );
  }
  assert.throws(
    () => doorCountsFromInput({ single_door_count: 2, double_door_count: 1 }),
    /must be one of/,
  );
});

test('0/0 remains a no-op for products without door selectors', () => {
  const input = { product_code: 'JM', variant_code: 'DEFAULT', single_door_count: 0, double_door_count: 0 };
  assert.deepEqual(normalizeDoorVariantInput(input), input);
});

test('formula door counts keep their database template behavior', () => {
  assert.equal(databaseVariantForDoorCounts({ single: 1, double: 0 }), 'SINGLE');
  assert.equal(databaseVariantForDoorCounts({ single: 0, double: 1 }), 'DOUBLE');
  assert.equal(databaseVariantForDoorCounts({ single: 1, double: 1 }), 'SINGLE');
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'JS_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 1 }),
    { product_code: 'JS_DOUBLE', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 1 },
  );
  assert.deepEqual(
    normalizeDoorVariantInput({ product_code: 'JA_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 2 }),
    { product_code: 'JA_SINGLE', variant_code: 'SINGLE', single_door_count: 0, double_door_count: 2 },
  );
});

test('every product accepts all five operator door combinations', () => {
  for (const [single, double] of VALID_DOOR_COMBINATIONS) {
    const normalized = normalizeDoorVariantInput({
      product_code: 'JC_EXP',
      variant_code: 'DEFAULT',
      single_door_count: single,
      double_door_count: double,
    });
    assert.equal(normalized.product_code, 'JC_EXP');
    assert.equal(normalized.variant_code, single > 0 ? 'SINGLE' : 'DOUBLE');
    assert.equal(normalized.single_door_count, single);
    assert.equal(normalized.double_door_count, double);
  }
});

test('quick quote reads SINGLE for all five JS/JP/JA/JE door combinations', () => {
  const expected = new Map([
    ['1/0', { JS: 'SINGLE', JP: 'SINGLE', JA: 'SINGLE', JE: 'SINGLE' }],
    ['2/0', { JS: 'SINGLE', JP: 'SINGLE', JA: 'SINGLE', JE: 'SINGLE' }],
    ['0/1', { JS: 'SINGLE', JP: 'SINGLE', JA: 'SINGLE', JE: 'SINGLE' }],
    ['0/2', { JS: 'SINGLE', JP: 'SINGLE', JA: 'SINGLE', JE: 'SINGLE' }],
    ['1/1', { JS: 'SINGLE', JP: 'SINGLE', JA: 'SINGLE', JE: 'SINGLE' }],
  ]);
  for (const [single, double] of VALID_DOOR_COMBINATIONS) {
    const key = `${single}/${double}`;
    for (const family of ['JS', 'JP', 'JA', 'JE']) {
      assert.equal(
        quickDoorVariantForCounts({ single, double }, family),
        expected.get(key)[family],
        `${family} ${key}`,
      );
      const normalized = normalizeQuickDoorVariantInput({
        product_code: `${family}_${double > 0 && single === 0 ? 'DOUBLE' : 'SINGLE'}`,
        variant_code: double > 0 && single === 0 ? 'DOUBLE' : 'SINGLE',
        single_door_count: single,
        double_door_count: double,
      });
      assert.equal(normalized.product_code, `${family}_SINGLE`, `${family} ${key} quick path`);
      assert.equal(normalized.variant_code, 'SINGLE', `${family} ${key} quick variant`);
    }
  }
  assert.deepEqual(
    normalizeQuickDoorVariantInput({ product_code: 'JE_DOUBLE', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 1 }),
    { product_code: 'JE_SINGLE', variant_code: 'SINGLE', product_family: 'JE', single_door_count: 0, double_door_count: 1 },
  );
  assert.deepEqual(
    normalizeQuickDoorVariantInput({ product_code: 'JE_DOUBLE', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 2 }),
    { product_code: 'JE_SINGLE', variant_code: 'SINGLE', product_family: 'JE', single_door_count: 0, double_door_count: 2 },
  );
  assert.equal(
    normalizeQuickDoorVariantInput({
      product_code: 'JS', variant_code: 'DOUBLE', single_door_count: 0, double_door_count: 1,
    }).product_code,
    'JS_SINGLE',
  );
});

test('automatic quick door surcharge and description APIs have been removed', () => {
  assert.equal('quickDoorVariantSurcharge' in doorRules, false);
  assert.equal('quickDoorVariantDescription' in doorRules, false);
  assert.equal('applyDoorVariantQuickPrice' in doorRules, false);
});
