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
  assert.match(source, /setObjectName\("attachmentCategoryCardShell"\)/);
  assert.match(source, /self\.category_grid\.addWidget\(card, index \/\/ 4, index % 4\)/);
  assert.match(source, /def prepare_fixed_base_quick_match/);
  assert.match(source, /类型：固定/);
  assert.match(source, /高度：\{height_text\} mm/);
  assert.match(source, /def open_attachment_category/);
  assert.match(source, /def back_attachment_category/);
  assert.match(source, /self\.table\.setVisible\(not at_category_level\)/);
  assert.doesNotMatch(source, /category_level1_combo/);

  assert.match(overlay, /def _install_attachment_default_selection_filters/);
  assert.match(overlay, /_install_attachment_default_selection_filters\(namespace\)/);
  assert.match(overlay, /self\.category_grid\.addWidget\(card, index \/\/ 4, index % 4\)/);
  assert.match(overlay, /parse_base_specification\(specification_text\(self\)\)/);
  assert.match(overlay, /match_fixed_base/);
  assert.match(overlay, /match_jp_side_panel/);
  assert.match(overlay, /match_default_a4_folder/);
  assert.match(overlay, /match_default_door_reinforcement/);
  assert.match(overlay, /match_default_ground_wire/);
  assert.match(overlay, /attachmentQuickMatchSelected/);
  assert.match(overlay, /attachmentQuickMatchCancelled/);
  assert.match(overlay, /def toggle_default_selection/);
  assert.match(overlay, /parent\.attachment_default_opt_outs/);
  assert.match(overlay, /def _sync_door_limiter_default_quantity/);
  assert.match(overlay, /attachment_default_quantity_overrides/);
  assert.match(overlay, /dialog_class\.apply_filter = apply_classification_filter/);
  assert.match(overlay, /_default_selection_filters_installed = True/);
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
  assert.match(hierarchy, /def parse_base_specification/);
  assert.match(hierarchy, /def match_fixed_base/);
  assert.match(hierarchy, /def match_default_light_switch/);
  assert.match(hierarchy, /def match_default_a4_folder/);
  assert.match(hierarchy, /def match_default_door_limiter/);
  assert.match(hierarchy, /def door_limiter_default_quantity/);
  assert.match(hierarchy, /\(1, 1\): 3/);
  assert.match(hierarchy, /def match_default_door_reinforcement/);
  assert.match(hierarchy, /def match_default_ground_wire/);
  assert.match(hierarchy, /def match_jp_side_panel/);
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
