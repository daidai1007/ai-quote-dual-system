import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('attachment dialog drills through responsive category cards before showing the table', async () => {
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
  assert.match(overlay, /def _attachment_category_column_count\(dialog\) -> int:/);
  assert.match(overlay, /if width >= 860:\s*return 4/);
  assert.match(overlay, /if width >= 680:\s*return 3\s*return 2/);
  assert.match(overlay, /row_index = index \/\/ column_count/);
  assert.match(overlay, /index % column_count/);
  assert.match(overlay, /parse_base_specification\(specification_text\(self\)\)/);
  assert.match(overlay, /match_fixed_base/);
  assert.match(overlay, /match_jp_side_panel/);
  assert.match(overlay, /match_default_a4_folder/);
  assert.match(overlay, /match_default_a3_folder/);
  assert.match(overlay, /QUICK_THREE_ROW_INSTALLATION_BEAM/);
  assert.match(overlay, /QUICK_FIXED_COLUMN/);
  assert.match(overlay, /match_default_door_reinforcement/);
  assert.match(overlay, /match_default_ground_wire/);
  assert.match(overlay, /match_default_copper_busbar/);
  assert.match(overlay, /attachmentQuickMatchSelected/);
  assert.match(overlay, /attachmentQuickMatchCancelled/);
  assert.match(overlay, /def toggle_default_selection/);
  assert.match(overlay, /parent\.attachment_default_opt_outs/);
  assert.match(overlay, /def _sync_door_limiter_default_quantity/);
  assert.match(overlay, /attachment_default_quantity_overrides/);
  assert.match(overlay, /search\.setPlaceholderText\("搜索附件名称、型号、规格、尺寸或价格方案"\)/);
  assert.match(overlay, /filter_path = \(\) if needle and not selected else selected/);
  assert.match(overlay, /self\.search_edit\.setVisible\(True\)/);
  assert.match(overlay, /panel_layout\.insertWidget\(0, search\)/);
  assert.match(overlay, /def _sync_quote_specification\(window, text: str, parser=None\)/);
  assert.match(overlay, /lambda value: _sync_quote_specification\(window, value, parser\)/);
  assert.match(overlay, /attachmentPriceSignPositive/);
  assert.match(overlay, /attachmentPriceSignNegative/);
  assert.match(overlay, /attachment_price_sign/);
  assert.match(overlay, /"attachment_category": category/);
  assert.match(overlay, /"category_level1": category/);
  assert.match(overlay, /"category_level2": category_level2\.text\(\)\.strip\(\) or None/);
  assert.match(overlay, /"category_level3": category_level3\.text\(\)\.strip\(\) or None/);
  assert.match(overlay, /getattr\(owner, "category_selection", \[\]\)/);
  assert.match(overlay, /"安装附件": \(QUICK_THREE_ROW_INSTALLATION_BEAM, QUICK_FIXED_COLUMN\)/);
  assert.match(overlay, /"资料盒": \(DEFAULT_A3_FOLDER, DEFAULT_A4_FOLDER\)/);
  assert.match(overlay, /quick_button\.setProperty\("attachmentQuickRule", quick_rule\)/);
  assert.match(overlay, /for quick_button in quick_buttons:\s*selection_layout\.addWidget\(quick_button\)/);
  assert.match(overlay, /match_attachment_size\(getattr\(self, "catalog", \[\]\), source, target\)/);
  assert.match(overlay, /rule in \(DEFAULT_DOOR_LIMITER, DEFAULT_DOOR_REINFORCEMENT\)/);
  assert.match(overlay, /dialog_class\.apply_filter = apply_classification_filter/);
  assert.match(overlay, /_default_selection_filters_installed = True/);
  assert.doesNotMatch(overlay, /category_level1_combo/);

  const approvedOrder = [
    '侧板', '安装板', '安装附件', '底座', '灯开关', '资料盒', '风机', '滤网', '门变形', '并柜件',
  ];
  let previousIndex = -1;
  for (const category of approvedOrder) {
    const index = hierarchy.indexOf(`"${category}"`);
    assert.ok(index > previousIndex, `${category} must follow the approved order`);
    previousIndex = index;
  }
  assert.match(
    hierarchy,
    /LEVEL1_TRAILING_ORDER = \(\s*"配置变形",\s*"控制柜附件",\s*"其他附件",\s*\)/,
  );
  assert.match(hierarchy, /LEVEL1_TRAILING_ORDER\.index\(value\)/);
  assert.match(hierarchy, /options\.append\(\{"value": "", "label": DIRECT_ITEMS_LABEL/);
  assert.match(hierarchy, /def parse_base_specification/);
  assert.match(hierarchy, /def match_fixed_base/);
  assert.match(hierarchy, /def match_default_light_switch/);
  assert.match(hierarchy, /def match_default_a4_folder/);
  assert.match(hierarchy, /def match_default_a3_folder/);
  assert.match(hierarchy, /def match_named_quick_attachment_size/);
  assert.match(hierarchy, /category_value\(item, 1\) == "三排纵梁"/);
  assert.match(hierarchy, /category_value\(item, 1\) == "三排纵梁" and name == "三排安装梁"/);
  assert.match(hierarchy, /def match_default_door_limiter/);
  assert.match(hierarchy, /def door_limiter_default_quantity/);
  assert.match(hierarchy, /\(1, 1\): 3/);
  assert.match(hierarchy, /def match_default_door_reinforcement/);
  assert.match(hierarchy, /def match_default_ground_wire/);
  assert.match(hierarchy, /def match_default_copper_busbar/);
  assert.match(hierarchy, /def match_jp_side_panel/);
  assert.match(hierarchy, /def match_attachment_size/);
  assert.match(hierarchy, /def completed_size_dimensions/);
  assert.match(hierarchy, /selected = dict\(matched\)/);
  assert.match(hierarchy, /def door_reinforcement_default_quantity/);
});

test('attachment category filters keep price editing and selection collection intact', async () => {
  const source = await fs.readFile(path.join(projectRoot, 'desktop_client', 'main.py'), 'utf8');
  const overlay = await fs.readFile(path.join(projectRoot, 'desktop_client', 'layout_refresh.py'), 'utf8');

  assert.match(source, /price_item\.setFlags\([^\n]*Qt\.ItemIsEditable/);
  assert.match(source, /quantity_item\.setFlags\([^\n]*Qt\.ItemIsEditable/);
  assert.match(source, /def collect_attachments/);
  assert.match(source, /item\["unit_price_override"\] = absolute_price/);
  assert.match(source, /item\["attachment_price_sign"\] = price_sign/);
  assert.doesNotMatch(overlay, /COL_PRICE[^\n]*setFlags/);
  assert.doesNotMatch(overlay, /COL_QUANTITY[^\n]*setFlags/);
  assert.match(overlay, /original_rebuild_table\(self\)/);
});
