import assert from 'node:assert/strict';
import test from 'node:test';
import {
  attachmentImageCatalogSql,
  attachmentImageTablesExistSql,
  normalizeAttachmentImages,
} from './attachment_image_query.mjs';

test('attachment image query is read-only and returns database bytes as base64', () => {
  assert.match(attachmentImageTablesExistSql, /to_regclass\('calc\.attachment_image_catalog'\)/);
  assert.match(attachmentImageCatalogSql, /FROM calc\.attachment_image_catalog c/);
  assert.match(attachmentImageCatalogSql, /FROM calc\.attachment_image_asset a/);
  assert.match(attachmentImageCatalogSql, /encode\(a\.image_data,'base64'\)/);
  assert.doesNotMatch(attachmentImageCatalogSql, /\b(?:INSERT|UPDATE|DELETE)\b/i);
});

test('attachment image response removes base64 whitespace and preserves empty rows', () => {
  const normalized = normalizeAttachmentImages([
    {
      item_name: ' 风机 ',
      match_mode: 'PREFIX',
      images: [{
        image_order: 1,
        mime_type: 'image/png',
        image_sha256: 'a'.repeat(64),
        data_base64: 'aGVs\nbG8=',
      }],
    },
    { item_name: '绑线条', match_mode: 'EXACT', images: [] },
  ]);
  assert.equal(normalized[0].item_name, '风机');
  assert.equal(normalized[0].match_mode, 'PREFIX');
  assert.equal(normalized[0].images[0].data_base64, 'aGVsbG8=');
  assert.deepEqual(normalized[1].images, []);
});

