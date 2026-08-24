import assert from 'node:assert/strict';
import test from 'node:test';
import { attachmentCatalogSql, decodeAttachmentCatalog } from './attachment_catalog_query.mjs';

const b64 = (value) => Buffer.from(value, 'utf8').toString('base64');

test('attachment catalogue decodes classification without changing price fields', () => {
  const [item] = decodeAttachmentCatalog([{
    attachment_price_id: 661,
    category_level1_b64: b64('安装板'),
    category_level2_b64: b64('JK安装板'),
    category_level3_b64: b64('JKZ151508'),
    item_name_b64: b64('JK安装板'),
    model_code_b64: b64('JKZ151508'),
    variant_b64: '',
    width_mm: 150,
    height_mm: 150,
    depth_mm: null,
    price: '14.0000',
    price_text_b64: b64('14'),
    unit_b64: b64('件'),
    price_source_b64: b64('表格价'),
    notes_b64: '',
  }]);

  assert.deepEqual(item, {
    attachment_price_id: 661,
    category_level1: '安装板',
    category_level2: 'JK安装板',
    category_level3: 'JKZ151508',
    item_name: 'JK安装板',
    model_code: 'JKZ151508',
    variant: '',
    width_mm: 150,
    height_mm: 150,
    depth_mm: null,
    price: '14.0000',
    price_text: '14',
    unit: '件',
    price_source: '表格价',
    notes: '',
  });
});

test('attachment catalogue SQL joins classification independently of price calculation', () => {
  assert.match(attachmentCatalogSql, /LEFT JOIN calc\.attachment_classification c/);
  assert.match(attachmentCatalogSql, /c\.category_level1/);
  assert.match(attachmentCatalogSql, /c\.category_level2/);
  assert.match(attachmentCatalogSql, /c\.category_level3/);
  assert.match(attachmentCatalogSql, /WHERE p\.is_active = TRUE/);
  assert.doesNotMatch(attachmentCatalogSql, /UPDATE\s+calc\.attachment_price/i);
});
