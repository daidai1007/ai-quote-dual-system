import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = fs.readFileSync(new URL('../desktop_client/scheme2_ui.py', import.meta.url), 'utf8');

test('照明灯行程开关下拉框显示线上五项', () => {
  const block = source.match(/LIGHT_SWITCH_OPTIONS = \(([\s\S]*?)\n\)/)?.[1] ?? '';
  const options = [...block.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(options, ['行程开关', '照明灯220V长款', '照明灯220V短款', '照明灯24V-0.28m', '照明灯24V-0.6m']);
  assert.match(source, /data\["item_name"\] = specification/);
  assert.match(source, /data\.pop\("model_code", None\)/);
});
