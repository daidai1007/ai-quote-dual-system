import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('attachment dialog drills through four-column category cards before showing the table', async () => {
  const source = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const overlay = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');
  const hierarchy = await fs.readFile(
    path.join(projectRoot, 'desktop_client', 'attachment_category_browser.py'),
    'utf8',
  );

  assert.match(source, /setObjectName\("attachmentCategoryCard"\)/);
  assert.match(source, /self\.category_grid\.addWidget\(button, index \/\/ 4, index % 4\)/);
  assert.match(source, /def open_attachment_category/);
  assert.match(source, /def back_attachment_category/);
  assert.match(source, /self\.table\.setVisible\(not at_category_level\)/);
  assert.doesNotMatch(source, /category_level1_combo/);

  assert.match(overlay, /def _install_attachment_classification_filters/);
  assert.match(overlay, /_install_attachment_classification_filters\(namespace\)/);
  assert.match(overlay, /self\.category_grid\.addWidget\(button, index \/\/ 4, index % 4\)/);
  assert.match(overlay, /dialog_class\.apply_filter = apply_classification_filter/);
  assert.match(overlay, /_classification_filters_installed = True/);
  assert.doesNotMatch(overlay, /category_level1_combo/);

  const approvedOrder = [
    '底座', '侧板', '三排纵梁', '安装板', '灯开关', '文件夹', '风机滤网',
    '门限位器', '门加强筋', '配置变形', '内门', '玻璃门', '安装条', '防雨顶',
    '接地线', '孔承板', '控制柜附件',
  ];
  let previousIndex = -1;
  for (const category of approvedOrder) {
    const index = hierarchy.indexOf(`"${category}"`);
    assert.ok(index > previousIndex, `${category} must follow the approved order`);
    previousIndex = index;
  }
  assert.match(hierarchy, /options\.append\(\{"value": "", "label": DIRECT_ITEMS_LABEL/);
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
