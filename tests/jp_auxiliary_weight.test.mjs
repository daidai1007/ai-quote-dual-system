import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {jpAuxiliaryWeight,JP_AUXILIARY_WEIGHT_BASIS} from '../api/jp_auxiliary_weight.mjs';
import {calculateCabinetAuxiliary,applyCabinetAuxiliary,createCabinetAuxiliaryService} from '../api/cabinet_auxiliary_service.mjs';

const input={product_code:'JP',width_mm:800,depth_mm:600,height_mm:1800};
const expected=(dimension,deduction,count)=>Math.round((dimension-deduction)*1.5*198*count*7.85*0.000001*1.2*1e8)/1e8;
test('latest four confirmed formulas use beams 4+4 and posts 2+2 at height minus 98',()=>{
 const weight=jpAuxiliaryWeight(input);assert.equal(weight.basis,JP_AUXILIARY_WEIGHT_BASIS);
 assert.deepEqual(weight.lines.map(row=>row.internal_quantity),[4,4,2,2]);
 assert.deepEqual(weight.lines.map(row=>row.weight_kg),[expected(800,88,4),expected(600,98,4),expected(1800,98,2),expected(1800,98,2)]);
 assert.equal(weight.weight_kg,32.63283936);assert.equal(weight.quantity_basis,'ONE_SET');
 assert.equal(jpAuxiliaryWeight({...input,quantity:9,waste_factor:9}).weight_kg,weight.weight_kg);
});
test('short dimensions cannot produce negative weight; invalid dimensions are rejected',()=>{
 assert.equal(jpAuxiliaryWeight({...input,width_mm:50,depth_mm:50,height_mm:50}).weight_kg,0);
 for(const value of [null,undefined,0,-1,Infinity,'bad'])assert.throws(()=>jpAuxiliaryWeight({...input,height_mm:value}));
 for(const product_code of ['JS','JA','JP_WIDE_EXP','JQ_EXP'])assert.equal(jpAuxiliaryWeight({...input,product_code}),null);
});
test('JP BOM prices/quantities are unchanged while response and persistence snapshot carry weight',()=>{
 const bundle=JSON.parse(readFileSync(new URL('../database/cabinet-auxiliary/generated/cabinet-auxiliary-bundle.json',import.meta.url)));
 const profile=bundle.profiles.find(p=>p.product_code==='JP'&&p.single_door_count===1&&p.material_codes.includes('SECC'));
 const lines=bundle.lines.filter(r=>r.profile_key===profile.profile_key);
 const aux=calculateCabinetAuxiliary(profile,lines,{...input,spray_unit_price:26});
 assert.equal(aux.self_made_weight.weight_kg,32.63283936);
 assert.equal(aux.lines.find(r=>r.item_name.startsWith('左立柱')).length_per_piece_m,1.712); // Pricing remains the original height-88 rule.
 assert.equal(aux.self_made_weight.lines[2].length_mm,1702); // New weight follows height-98 explicitly.
 const base={formula_cost:{material_cost:1,auxiliary_cost:0,labor_cost:1,spray_cost:1,attachment_fee:0},quick_quote:{total_cost:100}};
 const result=applyCabinetAuxiliary(base,aux);assert.equal(result.formula_cost.cabinet_auxiliary_weight_basis,JP_AUXILIARY_WEIGHT_BASIS);
 assert.equal(result.formula_cost.cabinet_auxiliary_self_made_weight_kg,32.63283936);assert.deepEqual(result.quick_quote,base.quick_quote);
 const plain=applyCabinetAuxiliary(base,{...aux,self_made_weight:undefined});
 for(const key of ['material_cost','auxiliary_cost','labor_cost','spray_cost','attachment_fee','management_fee','total_cost'])assert.equal(result.formula_cost[key],plain.formula_cost[key],key);
});

test('API service persists confirmed weight inside the existing auxiliary JSON snapshot',async()=>{
 const bundle=JSON.parse(readFileSync(new URL('../database/cabinet-auxiliary/generated/cabinet-auxiliary-bundle.json',import.meta.url)));
 const profile=bundle.profiles.find(p=>p.product_code==='JP'&&p.single_door_count===1&&p.material_codes.includes('SECC'));
 const lines=bundle.lines.filter(r=>r.profile_key===profile.profile_key);let update='';
 const service=createCabinetAuxiliaryService({runPsql:async sql=>{
  if(sql.startsWith('UPDATE')){update=sql;return '1';}
  return JSON.stringify({data_version:bundle.data_version,profile,lines,spray_unit_price:26});
 }});
 const auxiliary=await service.calculate({...input,quote_date:'2026-10-26',material_code:'SECC',single_door_count:1,double_door_count:0});
 assert.equal(auxiliary.self_made_weight.weight_kg,32.63283936);
 const result=applyCabinetAuxiliary({formula_cost:{material_cost:100,labor_cost:5,spray_cost:4,attachment_fee:0},quick_quote:{total_cost:300}},auxiliary);
 await service.persist('LOCAL-JP-001',result,auxiliary);
 assert.ok(update.includes('cabinet_auxiliary_snapshot='));
 assert.ok(update.includes(Buffer.from(JSON.stringify(auxiliary),'utf8').toString('hex')));
});
