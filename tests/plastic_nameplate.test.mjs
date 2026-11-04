import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {calculateAttachment, attachmentTotals, PRODUCT_CODES, MATERIAL_CODES} from '../api/attachment_cost.mjs';

test('plastic nameplate: face price 2, fixed cost 1.6, actual quantity, unchanged snapshot', () => {
  const item=JSON.parse(fs.readFileSync(new URL('./fixtures/plastic_nameplate.json',import.meta.url)));
  const before=structuredClone(item);
  for(const product_code of new Set(Object.values(PRODUCT_CODES).flat())) for(const material_code of MATERIAL_CODES) {
    for(const quantity of [1,2,5]) {
      const row=calculateAttachment({attachment_price_id:1238,quantity},item,item.rules,{
        quote_line_id:'SYNTHETIC-PLASTIC',product_code,material_code,width_mm:800,height_mm:1800,depth_mm:600,
        density_g_cm3:7.85,material_unit_price:5,spray_unit_price:26,coating_type:'橘纹',quote_date:'2026-11-03'});
      assert.equal(row.status,'FIXED');
      assert.equal(row.face_price,2);
      assert.equal(row.formula_unit_cost,1.6);
      assert.equal(row.quantity,quantity);
      assert.equal(row.quick_amount,2*quantity);
      assert.equal(row.formula_amount,1.6*quantity);
      assert.deepEqual(attachmentTotals([row]),{quick_attachment_fee:2*quantity,formula_attachment_fee:1.6*quantity,errors:[]});
    }
  }
  assert.deepEqual(item,before);
});
