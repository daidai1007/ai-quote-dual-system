import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {normalizeDoorVariantInput} from '../api/door_variant_rules.mjs';
import {jcCostProfile,selectedJcProfile} from '../api/jc_profile.mjs';
import {assertJcQuickMatch,jcQuickMatchSql} from '../api/jc_quick_match.mjs';
import {calculateCabinetMaterialFixed} from '../api/cabinet_material_service.mjs';
import {calculateCabinetSprayFixed} from '../api/cabinet_spray_service.mjs';
import {calculateCabinetAuxiliaryFixed} from '../api/cabinet_auxiliary_service.mjs';
import {calculateCabinetLabor} from '../api/cabinet_labor_service.mjs';

const read=path=>JSON.parse(fs.readFileSync(new URL(path,import.meta.url)));
const cases=read('./fixtures/jc_profiles.json');
const bundles=Object.fromEntries(['material','spray','auxiliary','labor'].map(kind=>[kind,
  read(`../database/cabinet-${kind}/generated/cabinet-${kind}-bundle.json`)]));

for(const row of cases) test(`${row.model}: user-confirmed face model selects ${row.profile} costs`,()=>{
  const input=normalizeDoorVariantInput({product_code:'JC_EXP',variant_code:'DEFAULT',model_code:row.model,
    material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:row.depth,
    single_door_count:1,double_door_count:0,material_unit_price:4.5,waste_factor:1.2,spray_unit_price:26});
  assert.equal(selectedJcProfile(input),row.profile);
  assert.equal(input.variant_code,row.profile);
  const expected=(kind)=>bundles[kind][kind==='labor'?'rules':'fixed_rules'].find(rule=>
    rule.product_code==='JC_EXP'&&rule.profile_code===row.profile&&Number(rule.depth_mm)===row.depth
    &&Number(rule.height_mm)===1600&&(rule.material_codes||[]).includes('SECC'));
  const env={...input,data_version:'offline-jc-profile',
    materials:[{material_code:'SECC',density_g_cm3:7.85,material_unit_price:4.5}]};
  const material=calculateCabinetMaterialFixed(bundles.material.fixed_rules,env);
  const spray=calculateCabinetSprayFixed(bundles.spray.fixed_rules,env);
  const aux=calculateCabinetAuxiliaryFixed(bundles.auxiliary.fixed_rules,env);
  const labor=calculateCabinetLabor(bundles.labor.rules,env,material);
  assert.equal(material.source_sheet,expected('material').source_sheet);
  assert.equal(spray.source_sheet,expected('spray').source_sheet);
  assert.equal(aux.auxiliary_cost,Math.round(Number(expected('auxiliary').auxiliary_cost)*100)/100);
  assert.equal(labor.labor_cost,Math.round(Number(expected('labor').labor_cost)*100)/100);
});

test('explicit selection is authoritative and is never overwritten by door counts or a legacy model',()=>{
  for(const profile of ['STANDARD','LUXURY'])for(const [single,double] of [[1,0],[0,1],[2,0],[0,2],[1,1]]){
    const input=normalizeDoorVariantInput({product_code:'JC_EXP',variant_code:profile,model_code:'JC601660-1',
      single_door_count:single,double_door_count:double});
    assert.equal(input.variant_code,profile);assert.equal(jcCostProfile(input),profile);
  }
});

test('direct legacy cost callers retain their previous suffix convention',()=>{
  assert.equal(jcCostProfile({model_code:'JC601660-1'}),'LUXURY');
  assert.equal(jcCostProfile({model_code:'JC601660-2'}),'STANDARD');
});

test('unknown profile cannot invent a face price; a missing same-profile price is actionable',()=>{
  const input={product_code:'JC_EXP',variant_code:'LUXURY'};
  assert.throws(()=>assertJcQuickMatch(input,{quick_quote:{base_price:null}}),/豪华型.*同型面价/);
  assert.doesNotThrow(()=>assertJcQuickMatch(input,{quick_quote:{base_price:0}}));
  assert.equal(jcQuickMatchSql({product_code:'JA_SINGLE'}),null);
});
