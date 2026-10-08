import test from 'node:test';
import assert from 'node:assert/strict';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {addAttachmentSnapshotSheet} from '../attachment_snapshot_export.mjs';
import {formulaAttachmentLineAmount,quickAttachmentLineAmount} from '../quick_discount_rules.mjs';

const lineId='11111111-1111-4111-8111-111111111111';
const environment={product_code:'JM',material_code:'SUS304',width_mm:800,height_mm:1400,depth_mm:250,
  coating_type:'橘纹',quote_date:'2026-10-08',cabinet_body_thickness_mm:1.5,waste_factor:1.2,
  ganged_cabinet_count:1,ganged_cabinets:[],quote_result:{
    formula_cost:{total_cost:100,attachment_fee:20,labor_cost:10,management_fee:1.3},
    quick_quote:{total_cost:200,attachment_fee:30}}};
const savedAttachment={attachment_price_id:99,quantity:1,attachment_price_sign:1,manual_inputs:{},
  attachment_selection_id:123,quote_line_id:lineId,status:'FIXED',catalog_version:'v2',item_name:'不锈钢门锁',
  category_level1:'其他附件',quick_amount:30,formula_amount:20};
const service=createAttachmentService({
  runPsql:async()=>JSON.stringify({environment,attachments:[savedAttachment]}),
  calculateBase:async()=>{throw new Error('not used');},env:{},
});
const item={...environment,name:'JM柜',model_code:'JM',attachment_contract:2,quote_line_id:lineId,
  labor_multiplier:1,ganged_cabinet_count:1,ganged_cabinets:[],attachments:[
    savedAttachment,{custom:true,item_name:'临时加强件',quantity:2,unit_price_override:6,
      quick_amount:12,formula_amount:7,attachment_price_sign:1},
  ]};

test('确认与导出保留人工新增附件，仅对目录附件校验ID',async()=>{
  const hydrated=(await service.hydrateDocument({items:[item]})).items[0];
  assert.equal(hydrated.attachments.length,2);
  const custom=hydrated.attachments[1];
  assert.equal(custom.custom,true);assert.equal(custom.attachment_price_id,undefined);
  assert.equal(custom.quick_amount,12);assert.equal(custom.formula_amount,7);
  assert.equal(hydrated.quick.attachment_fee,42);assert.equal(hydrated.quick.total_cost,212);
  assert.equal(hydrated.formula.attachment_fee,27);assert.equal(hydrated.formula.total_cost,107);
  assert.equal(quickAttachmentLineAmount(custom),12);
  assert.equal(formulaAttachmentLineAmount(custom),7);
});

test('未标记为人工新增的无ID附件仍被拒绝',async()=>{
  const invalid={...item,attachments:[savedAttachment,{item_name:'无编号附件',quantity:1}]};
  await assert.rejects(()=>service.hydrateDocument({items:[invalid]}),/必须提供有效 attachment_price_id/);
});

test('附件明细表显示人工新增行，不伪造数据库选择ID',()=>{
  const rows=[];
  const sheet={rowCount:0,columns:[],views:[],addRow(values){rows.push(values);this.rowCount=rows.length;return {};},
    getRow(){return {font:{},height:0};},eachRow(){}};
  const workbook={addWorksheet(){return sheet;}};
  addAttachmentSnapshotSheet(workbook,{items:[{...item,attachments:[savedAttachment,item.attachments[1]]}]});
  assert.equal(rows.length,3);
  assert.equal(rows[2][1],null);assert.equal(rows[2][5],'临时加强件');assert.equal(rows[2][24],'人工新增');
});
