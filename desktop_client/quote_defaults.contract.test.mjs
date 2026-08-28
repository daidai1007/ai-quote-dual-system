import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('new quote inputs default to carbon steel and orange texture', async () => {
  const defaults = await fs.readFile(path.join(projectRoot, 'desktop_client', 'quote_defaults.py'), 'utf8');
  const main = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const layout = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');
  const server = await fs.readFile(path.join(projectRoot, 'api', 'server.mjs'), 'utf8');

  assert.match(defaults, /DEFAULT_MATERIAL_CODE\s*=\s*["']SECC["']/);
  assert.match(defaults, /DEFAULT_COATING_TYPE\s*=\s*["']橘纹["']/);
  assert.match(main, /apply_default_quote_inputs\(self\)/);
  assert.match(layout, /restore_combo_selection\(coating_combo, selected, DEFAULT_COATING_TYPE\)/);
  assert.match(server, /const DEFAULT_COATING_TYPE = '橘纹';/);
  assert.ok((server.match(/coating_type \|\| DEFAULT_COATING_TYPE/g) || []).length >= 3);
});

test('current door counts replace only the door phrase in manual remarks', async () => {
  const rules = await fs.readFile(path.join(projectRoot, 'desktop_client', 'quote_remark_rules.py'), 'utf8');
  const main = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const layout = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');
  const exporter = await fs.readFile(path.join(projectRoot, 'export_dual_quote_workbook.mjs'), 'utf8');

  assert.match(rules, /\(1, 0\): "前单开门"/);
  assert.match(rules, /\(0, 1\): "前双开门"/);
  assert.match(rules, /\(2, 0\): "前后单开门"/);
  assert.match(rules, /\(0, 2\): "前后双开门"/);
  assert.match(rules, /\(1, 1\): "前单开门后双开门"/);
  assert.match(main, /replace_door_configuration_phrase/);
  assert.match(layout, /_install_door_remark_sync\(namespace\)/);
  assert.match(exporter, /replaceDoorConfigurationPhrase/);
});

test('manual freight persists independently and remains outside both discounts', async () => {
  const main = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const layout = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');
  const quickRules = await fs.readFile(path.join(projectRoot, 'quick_discount_rules.mjs'), 'utf8');
  const exporter = await fs.readFile(path.join(projectRoot, 'export_dual_quote_workbook.mjs'), 'utf8');

  assert.match(main, /field\(7, "运费", self\.freight_spin\)/);
  assert.match(main, /"freight_fee": self\.freight_spin\.value\(\)/);
  assert.match(main, /self\.freight_spin\.setValue\(float\(item\.get\("freight_fee", 0\) or 0\)\)/);
  assert.match(layout, /freight_total = freight_fee \* cabinets/);
  assert.match(layout, /item\["freight_fee"\] = freight_fee/);
  assert.match(quickRules, /\+ originalPriceAttachmentTotal \+ freightTotal/);
  assert.match(exporter, /"其他附件\/差额"\] : \[\]\), "运费", "折扣"/);
  assert.match(exporter, /values\[27\] = formulaBreakdown\.freightTotal/);
});
