import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('attachment dialog exposes linked three-level category filters', async () => {
  const source = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const overlay = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');

  assert.match(source, /self\.category_level1_combo = QComboBox/);
  assert.match(source, /self\.category_level2_combo = QComboBox/);
  assert.match(source, /self\.category_level3_combo = QComboBox/);
  assert.match(source, /def _level1_category_changed/);
  assert.match(source, /def _level2_category_changed/);
  assert.match(source, /def _category_filter_changed/);
  assert.match(source, /category_level1/);
  assert.match(source, /category_level2/);
  assert.match(source, /category_level3/);
  assert.match(source, /not category_matches/);

  assert.match(overlay, /def _install_attachment_classification_filters/);
  assert.match(overlay, /_install_attachment_classification_filters\(namespace\)/);
  assert.match(overlay, /"category_level1_combo"/);
  assert.match(overlay, /"category_level2_combo"/);
  assert.match(overlay, /"category_level3_combo"/);
  assert.match(overlay, /dialog_class\.apply_filter = apply_classification_filter/);
  assert.match(overlay, /_classification_filters_installed = True/);
});

test('attachment category filters keep price editing and selection collection intact', async () => {
  const source = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const overlay = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');

  assert.match(source, /price_item\.setFlags\([^\n]*Qt\.ItemIsEditable/);
  assert.match(source, /quantity_item\.setFlags\([^\n]*Qt\.ItemIsEditable/);
  assert.match(source, /def collect_attachments/);
  assert.match(source, /item\["unit_price_override"\] = price/);
  assert.doesNotMatch(overlay, /COL_PRICE[^\n]*setFlags/);
  assert.doesNotMatch(overlay, /COL_QUANTITY[^\n]*setFlags/);
  assert.match(overlay, /original_rebuild_table\(self\)/);
});
