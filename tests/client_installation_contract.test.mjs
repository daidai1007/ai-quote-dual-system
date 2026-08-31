import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (...parts) => readFile(path.join(root, ...parts), 'utf8');

test('client calculation remains actionable while formula templates load', async () => {
  const layout = await read('desktop_client', 'layout_refresh.py');
  assert.match(layout, /FORMULA_TEMPLATE_DEBOUNCE_MS\s*=\s*420/);
  assert.match(layout, /button\.setText\("模板读取中，可点击计算"\)/);
  assert.match(layout, /self\._pending_formula_calculation\s*=\s*True/);
  assert.match(layout, /读取完成后将自动继续计算/);
  assert.match(layout, /timer\.start\(FORMULA_TEMPLATE_BUSY_RECHECK_MS\)/);
});

test('client layout and diagnostics cover small high-DPI desktops', async () => {
  const layout = await read('desktop_client', 'layout_refresh.py');
  const launcher = await read('desktop_client', 'v3_launcher.py');
  assert.match(layout, /availableGeometry\(\)/);
  assert.match(layout, /_configure_quote_action_dock_density/);
  assert.match(layout, /mainScrollHost/);
  assert.match(layout, /host_layout\.addWidget\(dock, 0\)/);
  assert.match(launcher, /AIQuoteDualSystem" \/ "logs" \/ "client\.log/);
  assert.match(launcher, /RotatingFileHandler/);
  assert.match(launcher, /客户端启动失败/);
});

test('installer build requires Python 3.12 x64 and the dynamic V3 core', async () => {
  const build = await read('packaging', 'build_installer.ps1');
  const spec = await read('packaging', 'AIQuoteDualSystem_installer.spec');
  const nsis = await read('packaging', 'AIQuoteDualSystem.nsi');
  assert.doesNotMatch(build, /Program Files \(x86\)\\Python/);
  assert.match(build, /sys\.version_info\[:2\] == \(3, 12\)/);
  assert.match(build, /struct\.calcsize\('P'\) \* 8 == 64/);
  assert.match(build, /"main\.raw", "original\.pyz"/);
  assert.match(build, /sourceCoreFiles\.Count -ne \$stagedCoreFiles\.Count/);
  assert.match(spec, /AI_QUOTE_BUILD_VERSION/);
  assert.match(nsis, /AIQuoteDualSystem_Setup_v\$\{APP_VERSION\}\.exe/);
});
