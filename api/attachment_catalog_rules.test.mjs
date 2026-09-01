import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { normalizeCatalogAttachment } from './attachment_catalog_rules.mjs';

const serverSource = readFileSync(new URL('./server.mjs', import.meta.url), 'utf8');

test('manual attachment normalization keeps persistent catalogue fields', () => {
  assert.deepEqual(normalizeCatalogAttachment({ item_name: '  新铰链  ', price: 12.5 }), {
    attachment_category: '其他附件',
    category_level1: '其他附件',
    category_level2: '',
    category_level3: '',
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
    category_level1: '门锁', category_level2: '机械锁', category_level3: '标准型',
    item_name: '门锁', model_code: 'JS', variant: 'SINGLE',
    width_mm: 10, height_mm: 20, depth_mm: 30, price: 60,
    unit: '元/件', price_source: '人工核价', notes: '现场件',
  });
  assert.equal(item.width_mm, 10);
  assert.equal(item.height_mm, 20);
  assert.equal(item.depth_mm, 30);
  assert.equal(item.notes, '现场件');
  assert.equal(item.attachment_category, '门锁');
  assert.equal(item.category_level2, '机械锁');
  assert.equal(item.category_level3, '标准型');
});

test('catalog SQL writes the required legacy category and classification mapping', () => {
  const item = normalizeCatalogAttachment({
    category_level1: '安装板', category_level2: 'JK安装板',
    item_name: '安装条', price: 20,
  });
  assert.equal(item.attachment_category, '安装板');
  assert.match(serverSource, /INSERT INTO calc\.attachment_price \(\s*attachment_category,/);
  assert.match(serverSource, /source_file, source_sheet, source_row_no, is_active/);
  assert.match(serverSource, /sqlUnicodeText\('attachment_catalog_api'\)/);
  assert.match(serverSource, /sourceSheet: sqlUnicodeText\(item\.category_level1\)/);
  assert.match(
    serverSource,
    /\$\{values\.sourceFile\}, \$\{values\.sourceSheet\}, \$\{values\.sourceRow\}, TRUE/,
  );
  assert.match(serverSource, /AND attachment_category =/);
  assert.match(serverSource, /UPDATE calc\.attachment_classification classification/);
  assert.match(serverSource, /INSERT INTO calc\.attachment_classification \(/);
  assert.match(serverSource, /category_level1, category_level2, category_level3/);
});

test('manual attachment rejects unsafe or incomplete values', () => {
  assert.throws(() => normalizeCatalogAttachment({ item_name: '', price: 1 }), /required/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: null }), /price is required/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: '' }), /price is required/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: -1 }), /non-negative/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: '附件', price: 1, width_mm: 0 }), /positive/);
  assert.throws(() => normalizeCatalogAttachment({ item_name: 'x'.repeat(161), price: 1 }), /cannot exceed/);
});
