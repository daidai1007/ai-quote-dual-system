import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createAttachmentService} from '../api/attachment_service.mjs';

const fixture = JSON.parse(readFileSync(new URL('../test-output/attachment-cost-v2/api-client-fixtures.json', import.meta.url)));
const glass = fixture.catalog.items.find(row => row.item_name === '玻璃门' && row.category_level1 === '控制柜附件');
const children = [{width_mm:800,height_mm:1800,depth_mm:500}, {width_mm:600,height_mm:1800,depth_mm:500}];
const service = createAttachmentService({env:{},runPsql:async sql => {
  if(sql.includes('attachment_catalog_version')) return JSON.stringify([{data_version:'offline',status:'ACTIVE'}]);
  if(sql.includes('FROM (SELECT p.attachment_price_id')) return JSON.stringify([glass]);
  if(sql.includes('density_g_cm3')) return JSON.stringify({density_g_cm3:7.85,spray_unit_price:26});
  throw new Error('Unexpected offline query');
}});
const input = {product_code:'JP',material_code:'SECC',width_mm:1400,height_mm:1800,depth_mm:500,
  material_unit_price_override:4.2,quote_date:'2026-10-10',coating_type:'橘纹',ganged_cabinet_count:2,
  ganged_cabinets:children,ganged_cabinet_inputs:children};
const selection = (index,height,width) => ({attachment_price_id:glass.attachment_price_id,quantity:1,
  ganged_cabinet_index:index,manual_inputs:{玻璃门高度:height,玻璃门宽度:width}});

test('glass popup previews accept saved child context and actual manual glass sizes', async () => {
  const first = await service.preview({...input,attachments:[selection(0,500,400)]});
  const second = await service.preview({...input,attachments:[selection(1,600,300)]});
  assert.equal(first.attachments[0].status,'CALCULATED');
  assert.equal(second.attachments[0].status,'CALCULATED');
  assert.equal(first.attachments[0].formula_amount,11);
  assert.equal(second.attachments[0].formula_amount,9.9);
  assert.equal(second.attachments[0].environment.width_mm,600);
  assert.ok(first.attachments[0].quick_amount>0);
  assert.ok(second.attachments[0].quick_amount>0);
});

test('missing child context must not be interpreted as a successful zero price', async () => {
  await assert.rejects(service.preview({...input,ganged_cabinet_count:1,ganged_cabinets:[],
    ganged_cabinet_inputs:[],attachments:[selection(1,600,300)]}), /子柜不存在/);
});
