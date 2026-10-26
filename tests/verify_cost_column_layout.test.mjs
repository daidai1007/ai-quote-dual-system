import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = fs.readFileSync(new URL('../desktop_client/scheme2_ui.py', import.meta.url), 'utf8');

test('成本计算各列按表头顺序显示', () => {
  const displayOrder=[0,1,2,3,11,12,23,13,22,14,15,16,17,4,5,6,7,8,9,10,18,19,20,21];
  const actualOrder=source.match(/COST_DISPLAY_ORDER = \(([^)]+)\)/)[1].split(',').map(Number);
  assert.deepEqual(actualOrder,displayOrder);
  const expected = [
    '序号', '名称', '产品', '尺寸', '数量', '已选附件', '附件面价', '面价', '材料差价', '折扣系数',
    '报价', '报价总价', '成本单价', '材料成本', '辅材成本', '人工成本',
    '附件成本', '喷涂费用', '管理费用', '运费', '成本总价',
    '毛利率', '自制件重量', '成本明细',
  ];
  const headerBlock = source.match(/HEADERS = \(([\s\S]*?)\n\)/)?.[1] ?? '';
  const actual = [...headerBlock.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(actual, expected);
  assert.deepEqual([...actualOrder].sort((a,b)=>a-b),expected.map((_,index)=>index));
});
