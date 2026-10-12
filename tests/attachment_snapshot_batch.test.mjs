import assert from 'node:assert/strict';
import test from 'node:test';
import {createAttachmentService} from '../api/attachment_service.mjs';

const lineA='11111111-1111-4111-8111-111111111111';
const lineB='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const environment={product_code:'JP',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
  coating_type:'橘纹',quote_date:'2026-10-12',ganged_cabinet_count:1,ganged_cabinets:[],quote_result:{
    formula_cost:{total_cost:100,attachment_fee:20,labor_cost:10,management_fee:1.3},
    quick_quote:{total_cost:200,attachment_fee:30}}};
const attachment={attachment_price_id:99,item_name:'固定底座',quantity:1,attachment_price_sign:1,
  manual_inputs:{底座高度:100},status:'CALCULATED',formula_amount:20,quick_amount:30};
const saved={environment,attachments:[attachment]};
const item=(line=lineA)=>({...environment,name:'测试柜',quote_line_id:line,
  attachment_contract:2,attachments:[structuredClone(attachment)]});
function harness(snapshots={[lineA]:saved,[lineB]:saved}){
  const queries=[];
  const service=createAttachmentService({env:{},runPsql:async sql=>{
    queries.push(sql);
    assert.ok(!/\b(INSERT|UPDATE|DELETE|BEGIN|COMMIT)\b/.test(sql));
    // Model both the old per-row SELECT and the new set-based query.
    if(sql.includes('jsonb_object_agg'))return JSON.stringify(snapshots);
    const hex=/decode\('([0-9a-f]+)'/.exec(sql)?.[1];
    const id=hex&&Buffer.from(hex,'hex').toString('utf8').toLowerCase();
    return JSON.stringify(snapshots[id]||null);
  }});
  return {service,queries};
}

test('11 copied rows read a shared snapshot once and still hydrate all rows independently',async()=>{
  const h=harness();
  const result=await h.service.hydrateDocument({items:Array.from({length:11},(_,i)=>({...item(),name:`柜${i+1}`}))});
  assert.equal(h.queries.length,1);
  assert.equal(result.items.length,11);
  assert.equal(h.queries[0].split(Buffer.from(lineA).toString('hex')).length-1,1);
  result.items[0].attachments[0].manual_inputs.底座高度=999;
  assert.equal(result.items[1].attachments[0].manual_inputs.底座高度,100);
  assert.equal(saved.attachments[0].manual_inputs.底座高度,100);
});

test('different snapshots are loaded in one batch, but every row environment is checked',async()=>{
  const h=harness();
  await assert.rejects(h.service.hydrateDocument({items:[item(),{...item(lineB),width_mm:801}]}),/width_mm/);
  assert.equal(h.queries.length,1);
  assert.ok(h.queries[0].includes(Buffer.from(lineB).toString('hex')));
});

test('a copied row with different manual inputs cannot bypass per-row validation',async()=>{
  const h=harness();
  await assert.rejects(h.service.hydrateDocument({items:[item(),{...item(),attachments:[{
    ...attachment,manual_inputs:{底座高度:200}}]}]}),/人工参数已变化/);
  assert.equal(h.queries.length,1);
});

test('missing snapshots and invalid UUIDs are still rejected',async()=>{
  const h=harness({[lineA]:saved});
  await assert.rejects(h.service.hydrateDocument({items:[item(),item(lineB)]}),/报价行不存在/);
  assert.equal(h.queries.length,1);
  const invalid=harness();
  await assert.rejects(invalid.service.hydrateDocument({items:[item("x'); DELETE FROM calc.attachment_quote_line; --")]}),/报价行ID无效/);
  assert.equal(invalid.queries.length,0);
});

test('snapshot ERROR reports the original product line after batch loading',async()=>{
  const h=harness({[lineA]:saved,[lineB]:{...saved,attachments:[{...attachment,status:'ERROR',error:'底座高度无效'}]}});
  await assert.rejects(h.service.hydrateDocument({items:[item(),{...item(lineB),name:'第二柜'}]}),error=>{
    assert.equal(error.statusCode,422);
    assert.equal(error.issues[0].line_number,2);
    assert.equal(error.issues[0].product_name,'第二柜');
    assert.equal(error.issues[0].attachment_price_id,99);
    return true;
  });
  assert.equal(h.queries.length,1);
});

test('batch reuse keeps each row local attachment amounts and labor adjustments separate',async()=>{
  const h=harness();
  const result=await h.service.hydrateDocument({items:[{...item(),labor_multiplier:2,attachments:[attachment,
    {custom:true,item_name:'临时附件',quantity:1,quick_amount:6,formula_amount:5}]},item()]});
  assert.equal(result.items[0].formula.total_cost,116.3);
  assert.equal(result.items[0].quick.total_cost,206);
  assert.equal(result.items[1].formula.total_cost,100);
  assert.equal(result.items[1].quick.total_cost,200);
  assert.equal(result.items[1].attachments.length,1);
});

test('uppercase UUIDs resolve the same batch key and requests do not share stale cache',async()=>{
  const h=harness();
  await h.service.hydrateDocument({items:[item(lineB.toUpperCase()),item(lineB)]});
  await h.service.hydrateDocument({items:[item(lineB)]});
  assert.equal(h.queries.length,2);
  assert.equal(h.queries[0].split(Buffer.from(lineB).toString('hex')).length-1,1);
});

test('no catalogue snapshots means no extra snapshot query',async()=>{
  const h=harness();
  await h.service.hydrateDocument({items:[{name:'无附件',attachments:[]}]});
  assert.equal(h.queries.length,0);
});
