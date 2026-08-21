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
