import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeCatalogAttachment } from './attachment_catalog_rules.mjs';

test('manual attachment normalization keeps persistent catalogue fields', () => {
  assert.deepEqual(normalizeCatalogAttachment({ item_name: '  新铰链  ', price: 12.5 }), {
    item_name: '新铰链',
    model_code: null,
    variant: null,
    width_mm: null,
    height_mm: null,
    depth_mm: null,
    price: 12.5,
    price_text: '12.5',
    unit: '元',
    price_source: '人工新增',
    notes: null,
  });
});

test('manual attachment accepts optional dimensions and metadata', () => {
  const item = normalizeCatalogAttachment({
    item_name: '门锁', model_code: 'JS', variant: 'SINGLE',
    width_mm: 10, height_mm: 20, depth_mm: 30, price: 60,
    unit: '元/件', price_source: '人工核价', notes: '现场件',
  });
  assert.equal(item.width_mm, 10);
  assert.equal(item.height_mm, 20);
  assert.equal(item.depth_mm, 30);
  assert.equal(item.notes, '现场件');
});

test('manual attachment rejects unsafe or incomplete values', () => {
  assert.throws(() => normalizeCatalogAttachment({ item_name: '', price: 1 }), /required/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: -1 }), /non-negative/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: 1, width_mm: 0 }), /positive/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: 'x'.repeat(161), price: 1 }), /cannot exceed/);
});
