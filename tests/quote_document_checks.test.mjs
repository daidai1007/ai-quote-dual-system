import assert from 'node:assert/strict';
import test from 'node:test';
import {createAttachmentService} from '../api/attachment_service.mjs';

const lineId='11111111-1111-4111-8111-111111111111';
const environment={product_code:'JP',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
  coating_type:'橘纹',quote_date:'2026-10-12',cabinet_body_thickness_mm:1.5,waste_factor:1.2,
  ganged_cabinet_count:1,ganged_cabinets:[],quote_result:{
    formula_cost:{total_cost:100,attachment_fee:20},quick_quote:{total_cost:200,attachment_fee:0}}};
const attachment={attachment_price_id:99,item_name:'固定底座',quantity:1,attachment_price_sign:1,
  manual_inputs:{},status:'ERROR',error:'人工尺寸 底座高度必须是正数',formula_amount:null,quick_amount:0};
const item={...environment,name:'JP测试柜',quote_line_id:lineId,attachment_contract:2,
  attachments:[attachment],quantity:1};

test('read-only snapshot checks identify exact product line, attachment and missing parameter',async()=>{
  const queries=[];
  const service=createAttachmentService({env:{},runPsql:async sql=>{
    queries.push(sql);
    assert.ok(!/\b(INSERT|UPDATE|DELETE|BEGIN|COMMIT)\b/.test(sql),'preview checks must only read');
    return JSON.stringify({[lineId]:{environment,attachments:[attachment]}});
  }});
  await assert.rejects(service.hydrateDocument({items:[{...item,attachments:[]}]}),/人工参数已变化/);
  await assert.rejects(service.hydrateDocument({items:[{name:'正常柜',attachments:[]},item]}),error=>{
    assert.equal(error.statusCode,422);
    assert.deepEqual(error.issues,[{line_number:2,product_name:'JP测试柜',product_code:'JP',
      attachment_price_id:99,attachment_name:'固定底座',reason:'人工尺寸 底座高度必须是正数'}]);
    assert.match(error.message,/第2行报价（JP测试柜）的“固定底座”/);
    return true;
  });
  assert.ok(queries.length>0);
});

test('zero sale price is valid when the stored attachment cost has no error',async()=>{
  const valid={...attachment,status:'CALCULATED',error:null,formula_amount:20,formula_unit_cost:20};
  const service=createAttachmentService({env:{},runPsql:async()=>JSON.stringify({[lineId]:{environment,attachments:[valid]}})});
  const result=await service.hydrateDocument({items:[{...item,attachments:[valid]}]});
  assert.equal(result.items[0].attachments[0].quick_amount,0);
  assert.equal(result.items[0].attachments[0].formula_amount,20);
});

test('local repricing cannot hide an error retained in the authoritative snapshot',async()=>{
  const service=createAttachmentService({env:{},runPsql:async()=>JSON.stringify({[lineId]:{environment,attachments:[attachment]}})});
  await assert.rejects(service.hydrateDocument({items:[{...item,
    attachments:[{...attachment,status:'CALCULATED',error:null,formula_amount:99}]}]}),error=>{
    assert.equal(error.issues[0].attachment_name,'固定底座');
    assert.match(error.issues[0].reason,/底座高度/);
    return true;
  });
});
