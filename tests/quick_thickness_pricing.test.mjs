import test from 'node:test';
import assert from 'node:assert/strict';
import {applyQuickThickness,applyQuickThicknessResult,quickThicknessMultiplier} from '../api/quick_thickness_pricing.mjs';
import {createQuickMatchOverrideService} from '../api/quick_match_override.mjs';
import {calculateGangedBatch} from '../api/ganged_quote_service.mjs';
import {quickOrderLineBreakdown} from '../quick_discount_rules.mjs';

const environment=(product_code='JS_SINGLE',cabinet_body_thickness_mm=2)=>({product_code,cabinet_body_thickness_mm});
const quote=()=>({base_price:1000,attachment_fee:100,total_cost:1100,matched_experience:{quick_base_price:900}});
test('only JS JA JE and their door variants at 2.0mm increase the cabinet face',()=>{
 for(const code of ['JS','JS_SINGLE','JS_DOUBLE','JA','JA_SINGLE','JE','JE_SINGLE','JE_DOUBLE']){
  const input=quote(),before=structuredClone(input),result=applyQuickThickness(input,environment(code));
  assert.equal(result.base_price,1200,code);assert.equal(result.total_cost,1300);
  assert.equal(result.attachment_fee,100);assert.deepEqual(input,before);
  assert.equal(result.matched_experience.quick_base_price,900,'catalogue provenance remains raw');
 }
 for(const code of ['JP','JP_SINGLE','JM','JK','JC_EXP','JQ_EXP','JS_WIDE_EXP','JP_WIDE_EXP'])
  assert.equal(applyQuickThickness(quote(),environment(code)).base_price,1000,code);
 for(const thickness of [undefined,null,1.5,2.5,2.01,3])assert.equal(quickThicknessMultiplier({product_code:'JS',cabinet_body_thickness_mm:thickness}),1);
 assert.equal(quickThicknessMultiplier(environment('JE','2.0')),1.2);
});
test('refresh and toggle never compound; attachment, freight, discount and quantity stay on existing rules',()=>{
 const env=environment(),once=applyQuickThickness(quote(),env);
 assert.deepEqual(applyQuickThickness(once,env),once);
 assert.equal(applyQuickThickness(once,environment('JS',1.5)).base_price,1000);
 assert.equal(applyQuickThickness(once,env,{sourceBase:500}).base_price,600,'manual size is a fresh original base');
 const attachment={item_name:'接地线',quantity:1,quick_amount:100};
 const line=quickOrderLineBreakdown({quote:once,attachments:[attachment],discount:.5,cabinetQuantity:3,freightFee:50});
 assert.equal(line.equivalentUnitTotal,750);assert.equal(line.lineTotal,2250);
 assert.equal(applyQuickThickness({base_price:0,attachment_fee:10,total_cost:10},env).total_cost,10);
 const missing={base_price:null,total_cost:null,attachment_fee:0};assert.deepEqual(applyQuickThickness(missing,env),missing);
});
test('formula costs are untouched and mixed ganged children are adjusted individually once',async()=>{
 const cabinets=[environment('JS'),environment('JA',1.5),environment('JP')];
 const results=cabinets.map(env=>applyQuickThicknessResult({quick_quote:quote(),formula_cost:{material_cost:100,auxiliary_cost:20,labor_cost:30,spray_cost:10,attachment_fee:0}},env));
 for(const result of results)assert.deepEqual(result.formula_cost,{material_cost:100,auxiliary_cost:20,labor_cost:30,spray_cost:10,attachment_fee:0});
 const output=await calculateGangedBatch({cabinets,attachmentTotal:70,areaTotal:null,attachment:null},
  {calculateChild:async child=>results[cabinets.indexOf(child)]});
 assert.equal(output.quick_quote.base_price,3200);assert.equal(output.quick_quote.total_cost,3270);
 assert.deepEqual(output.ganged_cabinet_results.map(row=>row.quick_quote.base_price),[1200,1000,1000]);
});
test('manual matched sizes retain the rule for ordinary and mixed ganged snapshots',async()=>{
 for(const count of [1,2]){
  const env={...environment('JA'),quote_date:'2026-10-30',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
   ganged_cabinet_count:count,ganged_cabinets:count===2?[{...environment('JA'),width_mm:800,height_mm:1800,depth_mm:600},
    {...environment('JP'),width_mm:800,height_mm:1800,depth_mm:600}]:[],
   quote_result:{quick_quote:applyQuickThickness(quote(),environment('JA')),formula_cost:{total_cost:100}}};
  if(count===2)env.quote_result.ganged_cabinet_results=[{quick_quote:quote()},{quick_quote:quote()}];
  let saved;
  const service=createQuickMatchOverrideService({runPsql:async sql=>{
   if(sql.startsWith("SELECT jsonb_build_object('environment'"))return JSON.stringify({environment:env,quote_id:'LOCAL-THICKNESS'});
   if(sql.startsWith('SELECT coalesce(jsonb_agg'))return JSON.stringify(Array.from({length:count},(_,i)=>({cabinet_index:i,base_price:500,
    dimension_distance:0,matched_experience:{product_code:i?'JP_SINGLE':'JA_SINGLE'}})));
   const encoded=[...sql.matchAll(/decode\('([a-f0-9]+)','hex'\)/g)].map(m=>Buffer.from(m[1],'hex').toString()).find(s=>s.startsWith('{'));
   saved=JSON.parse(encoded);return JSON.stringify({quote_line_id:saved.quote_line_id,quick_quote:saved.quote_result.quick_quote});
  }});
  const result=await service({quote_line_id:'11111111-1111-4111-8111-111111111111',matched_sizes:Array.from({length:count},()=>({width_mm:800,height_mm:1800,depth_mm:600}))});
  assert.equal(result.quick_quote.base_price,count===1?600:1100);
  assert.equal(result.quick_quote.total_cost,count===1?700:1200);
  if(count===2)assert.deepEqual(saved.quote_result.ganged_cabinet_results.map(row=>row.quick_quote.base_price),[600,500]);
 }
});
