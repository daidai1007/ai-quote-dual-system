import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

test('signed installation-board migration keeps source prices positive and creates five door-change items', async () => {
  const [sql, server] = await Promise.all([
    fs.readFile(
      path.join(root, 'database', 'migrations', 'signed_installation_board_and_door_transformations.sql'),
      'utf8',
    ),
    fs.readFile(path.join(root, 'api', 'server.mjs'), 'utf8'),
  ]);
  assert.match(sql, /ADD COLUMN IF NOT EXISTS price_sign SMALLINT/);
  assert.match(sql, /price_sign IN \(-1, 1\)/);
  assert.match(sql, /COALESCE\(s\.unit_price, p\.price\) \* s\.price_sign/);
  assert.match(sql, /p_price_sign SMALLINT DEFAULT 1/);
  assert.match(sql, /negative price_sign is allowed only for an installation board/);
  assert.match(sql, /Move the former one-off item into 门变形/);
  assert.match(sql, /item_name = 'JS、JP单开门改为上下门'[\s\S]*SET is_active = TRUE,[\s\S]*attachment_category = '门变形'/);
  assert.match(sql, /INSERT INTO calc\.attachment_price \([\s\S]*attachment_category[\s\S]*SELECT[\s\S]*'门变形', wanted\.item_name/);
  assert.match(sql, /source_file, source_sheet, source_row_no/);
  assert.match(sql, /'signed_installation_board_and_door_transformations\.sql', '门变形'/);
  assert.match(sql, /wanted\.source_row_no, TRUE/);
  assert.match(sql, /price\.item_name = 'JS、JP单开门改为上下门'/);
  assert.match(sql, /SET category_level1 = '门变形'/);
  for (const [name, price] of [
    ['JS、JP后背板改为单开门', 150],
    ['JS、JP后背板改为双开门', 270],
    ['JS、JP单开门改为双开门', 150],
    ['JA、JE单开门改为双开门', 60],
  ]) {
    assert.match(sql, new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[^\\n]*${price}`));
  }
  assert.match(sql, /category_level1 = '门变形'/);
  assert.match(sql, /ranked_legacy/);
  assert.match(sql, /duplicate_rank > 1/);
  assert.match(sql, /item_name NOT IN/);
  assert.match(sql, /All other 配置变形 rows keep/);
  assert.match(server, /attachment_price_sign/);
  assert.match(server, /negative price sign only for an installation board/);
  assert.match(server, /::SMALLINT/);
});
