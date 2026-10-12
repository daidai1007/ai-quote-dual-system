import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createAttachmentService,attachmentInput} from '../api/attachment_service.mjs';

const fixture=JSON.parse(readFileSync(new URL('../test-output/attachment-cost-v2/api-client-fixtures.json',import.meta.url)));
const glass=fixture.catalog.items.find(row=>row.item_name==='玻璃门'&&row.category_level1==='控制柜附件');
const oldId='11111111-1111-4111-8111-111111111111';
function harness(children=[],catalogItem=glass){
  const failed=children.length?children.map((_child,index)=>({attachment_price_id:glass.attachment_price_id,
    item_name:'玻璃门',quantity:1,attachment_price_sign:1,manual_inputs:{},ganged_cabinet_index:index,
    environment:{product_code:index?'JP_DOUBLE':'JP_SINGLE'},status:'ERROR',quick_amount:100,formula_amount:null,
    error:'人工尺寸 玻璃门高度必须是正数'})):[{attachment_price_id:glass.attachment_price_id,item_name:'玻璃门',
    quantity:1,attachment_price_sign:1,manual_inputs:{},status:'ERROR',quick_amount:100,formula_amount:null,
    error:'人工尺寸 玻璃门高度必须是正数'}];
  const environment={product_code:'JP_SINGLE',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:400,
    coating_type:'橘纹',quote_date:'2026-10-12',cabinet_body_thickness_mm:1.5,waste_factor:1.2,
    material_unit_price:4.2,spray_unit_price:26,density_g_cm3:7.85,
    ganged_cabinet_count:children.length||1,ganged_cabinets:children,quote_result:{quote_id:'original',
      formula_cost:{material_cost:100,auxiliary_cost:10,labor_cost:20,spray_cost:15,management_fee:5,
        attachment_fee:null,total_cost:null},quick_quote:{base_price:500,attachment_fee:100,total_cost:600},
      risk_flags:[{code:'attachment_error',message:'玻璃门高度缺失'}]}};
  for(const row of failed){
    row.attachment_price_id=catalogItem.attachment_price_id;
    row.item_name=catalogItem.item_name;
  }
  const old={environment,attachments:failed},queries=[];
  let stored=null;
  const service=createAttachmentService({env:{},runPsql:async sql=>{
    queries.push(sql);
    if(sql.startsWith('BEGIN;')){
      assert.ok(!/\bUPDATE\b|attachment_price\s*\(|quote_history/.test(sql),'must not edit prices, old snapshots or history');
      const objects=[...sql.matchAll(/decode\('([0-9a-f]+)'/g)].flatMap(match=>{
        try{return [JSON.parse(Buffer.from(match[1],'hex').toString('utf8'))];}catch{return [];}
      });
      stored={environment:objects.find(value=>value.quote_result),
              attachments:objects.filter(value=>value.attachment_price_id&&value.status)};
      return JSON.stringify(stored);
    }
    if(sql.includes('FROM calc.attachment_quote_line')){
      return JSON.stringify(sql.includes(Buffer.from(oldId).toString('hex'))?old:stored);
    }
    if(sql.includes('attachment_catalog_version'))return JSON.stringify([{data_version:'offline',status:'ACTIVE'}]);
    if(sql.includes('FROM (SELECT p.attachment_price_id'))return JSON.stringify([catalogItem]);
    if(sql.includes('density_g_cm3'))return JSON.stringify({density_g_cm3:7.85,spray_unit_price:26});
    throw new Error('unexpected query');
  }});
  return {service,environment,old,queries,get stored(){return stored;}};
}
const selection=(manual,index)=>({attachment_price_id:glass.attachment_price_id,quantity:1,manual_inputs:manual,
  ...(index===undefined?{}:{ganged_cabinet_index:index})});

test('filled glass dimensions create a fresh valid snapshot; old ERROR remains unchanged',async()=>{
  const h=harness(),unchanged=structuredClone(h.old);
  const result=await h.service.recalculateLine({quote_line_id:oldId,environment:h.environment,
    attachments:[selection({玻璃门宽度:400,玻璃门高度:400})],base_result:{formula_cost:{total_cost:999999}}});
  assert.notEqual(result.quote_line_id,oldId);
  assert.equal(result.attachments[0].status,'CALCULATED');
  assert.equal(result.attachments[0].formula_amount,8.8);
  assert.equal(result.formula_cost.total_cost,158.8);
  assert.equal(result.risk_flags.some(risk=>risk.code==='attachment_error'),false);
  assert.deepEqual(h.old,unchanged);
  const item={...h.environment,quote_line_id:result.quote_line_id,attachment_contract:2,
    attachments:result.attachments.map(attachmentInput)};
  const checked=await h.service.hydrateDocument({items:[item]});
  assert.equal(checked.items[0].attachments[0].formula_amount,8.8);
});

test('missing manual dimensions still fail and never write a replacement snapshot',async()=>{
  const h=harness();
  await assert.rejects(h.service.recalculateLine({quote_line_id:oldId,attachments:[selection({})]}),error=>{
    assert.equal(error.statusCode,422);
    assert.equal(error.issues[0].attachment_name,'玻璃门');
    return true;
  });
  assert.equal(h.queries.some(sql=>sql.startsWith('BEGIN;')),false);
});

test('ganged refresh keeps each child environment and separate glass sizes',async()=>{
  const children=[{width_mm:800,height_mm:1800,depth_mm:500},{width_mm:600,height_mm:1800,depth_mm:500}];
  const h=harness(children);
  const result=await h.service.recalculateLine({quote_line_id:oldId,environment:h.environment,attachments:[
    selection({玻璃门宽度:400,玻璃门高度:500},0),selection({玻璃门宽度:300,玻璃门高度:600},1)]});
  assert.deepEqual(result.attachments.map(row=>row.formula_amount),[11,9.9]);
  assert.deepEqual(result.attachments.map(row=>row.environment.product_code),['JP_SINGLE','JP_DOUBLE']);
  assert.deepEqual(h.stored.environment.ganged_cabinets,children);
});

test('changed cabinet data cannot reuse an old cabinet result',async()=>{
  const h=harness();
  await assert.rejects(h.service.recalculateLine({quote_line_id:oldId,environment:{...h.environment,width_mm:900},
    attachments:[selection({玻璃门宽度:400,玻璃门高度:400})]}),/柜体参数已变化/);
  assert.equal(h.queries.some(sql=>sql.startsWith('BEGIN;')),false);
});

test('filled segment-board height creates a valid snapshot using the actual cabinet width',async()=>{
  const board=fixture.catalog.items.find(row=>row.item_name==='分段板');
  const h=harness([],board),unchanged=structuredClone(h.old);
  const result=await h.service.recalculateLine({quote_line_id:oldId,environment:h.environment,
    attachments:[{attachment_price_id:board.attachment_price_id,quantity:2,manual_inputs:{分段板高度:150}}]});
  const expected=(800-102)*150*7.85*1.5*.000001*4.2-5.3+14.5*.8+80*.15;
  assert.equal(result.attachments[0].status,'CALCULATED');
  assert.ok(Math.abs(result.attachments[0].formula_unit_cost-expected)<1e-8);
  assert.equal(result.attachments[0].formula_amount,Number((expected*2).toFixed(2)));
  assert.ok(result.attachments[0].quick_amount>0);
  const checked=await h.service.hydrateDocument({items:[{...h.environment,attachment_contract:2,
    quote_line_id:result.quote_line_id,attachments:result.attachments.map(attachmentInput)}]});
  assert.equal(checked.items[0].attachments[0].manual_inputs.分段板高度,150);
  assert.deepEqual(h.old,unchanged);
});
