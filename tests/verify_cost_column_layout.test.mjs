import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = fs.readFileSync(new URL('../desktop_client/scheme2_ui.py', import.meta.url), 'utf8');

test('成本计算各列按表头顺序显示', () => {
  const displayOrder=[0,1,2,3,11,12,23,24,22,14,15,16,17,4,5,6,7,8,9,10,18,19,20,21,25,26,27,28,29];
  const actualOrder=source.match(/COST_DISPLAY_ORDER = \(([^)]+)\)/)[1].split(',').map(Number);
  assert.deepEqual(actualOrder,displayOrder);
  const expected = [
    '序号', '名称', '产品', '尺寸', '数量', '已选附件', '附件面价', '固定报价', '材料差价', '折扣系数',
    '报价', '报价总价', '成本单价', '材料成本', '辅材成本', '人工成本',
    '附件成本', '喷涂费用', '管理费用', '运费', '成本总价',
    '毛利率', '自制件重量', '成本明细', '折扣面价', '净利率', '制造成本', '报价运费', '税费',
  ];
  const headerBlock = source.match(/HEADERS = \(([\s\S]*?)\n\)/)?.[1] ?? '';
  const actual = [...headerBlock.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(actual, expected);
  // Canonical field 13 remains the old undiscounted face for existing export
  // and discount-editor callers; it is no longer a displayed cost column.
  assert.deepEqual([...actualOrder].sort((a,b)=>a-b),Array.from({length:30},(_,i)=>i).filter(i=>i!==13));
  const visual=source.match(/COST_VISUAL_ORDER = \(([^)]+)\)/)[1].split(',').map(Number);
  assert.deepEqual(visual.slice(visual.indexOf(7),visual.indexOf(9)+1),[7,24,9]);
  assert.deepEqual(visual.slice(visual.indexOf(18),visual.indexOf(19)+1),[18,28,19]);
  assert.deepEqual(visual.slice(visual.indexOf(10),visual.indexOf(11)+1),[10,27,11]);
  assert.deepEqual(visual.slice(visual.indexOf(14),visual.indexOf(15)+1),[14,26,15]);
  assert.deepEqual(visual.slice(visual.indexOf(21),visual.indexOf(22)+1),[21,25,22]);
});
