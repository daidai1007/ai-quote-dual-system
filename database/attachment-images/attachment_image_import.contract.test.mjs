import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'generated', 'attachment-image-manifest.json'), 'utf8'));
const createSql = fs.readFileSync(path.join(root, 'web', '01-create.sql'), 'utf8');
const importSql = fs.readFileSync(path.join(root, 'web', '02-import.sql'), 'utf8');

test('Word attachment image import preserves reviewed counts and missing images', () => {
  assert.equal(manifest.source_document_sha256, '2eeaf27a213cc98b32c5629f5d94bb036479b05bf86b3030b4052c69925cf861');
  assert.equal(manifest.catalog_count, 50);
  assert.equal(manifest.image_count, 28);
  assert.equal(manifest.missing_image_count, 24);
  assert.equal(manifest.items.filter((item) => item.match_mode === 'PREFIX').length, 2);
  assert.equal(manifest.items.find((item) => item.item_name === '照明灯/行程开关').images.length, 2);
  assert.equal(manifest.items.find((item) => item.item_name === '并柜件').images.length, 2);
  assert.equal(manifest.items.find((item) => item.item_name === '绑线条').images.length, 0);
});

test('image schema is independent of price and quote calculations', () => {
  assert.match(createSql, /CREATE TABLE IF NOT EXISTS calc\.attachment_image_catalog/);
  assert.match(createSql, /CREATE TABLE IF NOT EXISTS calc\.attachment_image_asset/);
  assert.match(importSql, /INSERT INTO calc\.attachment_image_catalog/);
  assert.match(importSql, /INSERT INTO calc\.attachment_image_asset/);
  assert.doesNotMatch(importSql, /(?:UPDATE|INSERT INTO|DELETE FROM)\s+calc\.(?:attachment_price|attachment_selection|dual_quote_result)/i);
});

