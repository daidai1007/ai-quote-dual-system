import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {applyCabinetAuxiliary,calculateCabinetAuxiliary,calculateCabinetAuxiliaryFixed} from '../api/cabinet_auxiliary_service.mjs';

const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-auxiliary/generated/cabinet-auxiliary-bundle.json',import.meta.url)));
const get=(product,single,double,material='SECC')=>{const profile=bundle.profiles.find(p=>p.product_code===product&&p.single_door_count===single&&p.double_door_count===double&&p.material_codes.includes(material));return [profile,bundle.lines.filter(l=>l.profile_key===profile.profile_key)];};

test('auxiliary formulas take width height and depth from the current quote row',()=>{
  const [profile,lines]=get('JS',1,0);
  const first=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:800,height_mm:2200,depth_mm:600,spray_unit_price:26});
  const second=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:1000,height_mm:2400,depth_mm:600,spray_unit_price:26});
  const firstPipes=first.lines.filter(x=>x.item_name==='方管');
  assert.deepEqual(firstPipes.map(x=>x.length_per_piece_m),[2.03,.653]);
  assert.ok(second.auxiliary_cost>first.auxiliary_cost);
});

test('height conditional lock rows are selected without cached spreadsheet inputs',()=>{
  const [profile,lines]=get('JA',1,0);
  const low=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:600,height_mm:800,depth_mm:250,spray_unit_price:26});
  const high=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:600,height_mm:801,depth_mm:250,spray_unit_price:26});
  assert.equal(low.lines.find(x=>x.item_name==='MS821').internal_quantity,0);
  assert.equal(low.lines.find(x=>x.item_name==='MS813').internal_quantity,1);
  assert.equal(high.lines.find(x=>x.item_name==='MS821').internal_quantity,1);
  assert.equal(high.lines.find(x=>x.item_name==='MS813').internal_quantity,0);
});

test('auxiliary builder accepts general height thresholds and the runtime keeps strict boundaries',()=>{
  const builder=fs.readFileSync(new URL('../scripts/build_cabinet_auxiliary_rules.mjs',import.meta.url),'utf8');
  assert.match(builder,/IF\\\(A5>\(\[0-9\.\]\+\),\(\[0-9\.\]\+\),\(\[0-9\.\]\+\)\\\)/);
  assert.doesNotMatch(builder,/IF\\\(A5>800,1,0\\\)/);

  const profile={product_code:'JA',single_door_count:1,double_door_count:0,source_sheet:'JA1'};
  const lines=[{line_id:1,line_no:1,item_name:'高度条件辅材',quantity_rule:{kind:'HEIGHT_GT',threshold:1000,when_true:2,when_false:0},
    unit_price:3,cost_kind:'UNIT',source_sheet:'JA1',source_row_no:5}];
  const environment={data_version:'aux-test',width_mm:600,depth_mm:250,spray_unit_price:0};
  const boundary=calculateCabinetAuxiliary(profile,lines,{...environment,height_mm:1000});
  const above=calculateCabinetAuxiliary(profile,lines,{...environment,height_mm:1001});
  assert.equal(boundary.lines[0].internal_quantity,0);
  assert.equal(above.lines[0].internal_quantity,2);
});

test('JE stainless lifting ring uses the revised price without changing lock rods',()=>{
  const [profile,lines]=get('JE',1,0,'SUS304');
  const liftingRing=lines.find(line=>line.item_name==='吊环');
  const lockRods=lines.filter(line=>line.item_name==='锁杆-大锁头');
  assert.equal(profile.source_sheet,'JE1 (2)');
  assert.equal(liftingRing.unit_price,5.5);
  assert.deepEqual(liftingRing.quantity_rule,{kind:'HEIGHT_GT',threshold:1000,when_true:2,when_false:0});
  assert.equal(lockRods.length,2);
  assert.deepEqual(lockRods.map(line=>line.unit_price),[5.8,5.8]);
});

test('JP auxiliary frame spray uses current spray price and zero for no spray',()=>{
  const [profile,lines]=get('JP',1,0),environment={data_version:bundle.data_version,width_mm:800,height_mm:1800,depth_mm:400};
  const a=calculateCabinetAuxiliary(profile,lines,{...environment,spray_unit_price:10});
  const b=calculateCabinetAuxiliary(profile,lines,{...environment,spray_unit_price:30});
  const none=calculateCabinetAuxiliary(profile,lines,{...environment,spray_unit_price:0});
  assert.equal(Math.round((b.auxiliary_cost-a.auxiliary_cost)*100)/100,Math.round(a.auxiliary_spray_area_m2*20*100)/100);
  assert.equal(none.auxiliary_spray_cost,0);
});

test('auxiliary replacement is formula-only',()=>{
  const quick={base_price:1000,attachment_fee:20,total_cost:1020};
  const auxiliary={data_version:'aux-v1',auxiliary_cost:80,auxiliary_spray_area_m2:0,auxiliary_spray_cost:0,source_sheet:'JA1',lines:[]};
  const result=applyCabinetAuxiliary({formula_cost:{auxiliary_cost:30,total_cost:500},quick_quote:quick},auxiliary);
  assert.equal(result.formula_cost.total_cost,550);assert.deepEqual(result.quick_quote,quick);
});

test('all 32 material profiles and 510 BOM rows execute',()=>{
  assert.equal(bundle.profiles.length,32);assert.equal(bundle.lines.length,510);
  for(const profile of bundle.profiles){
    const lines=bundle.lines.filter(line=>line.profile_key===profile.profile_key);
    const result=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:1000,height_mm:2200,depth_mm:600,spray_unit_price:26});
    assert.equal(result.lines.length,lines.length,profile.source_sheet);assert.ok(result.auxiliary_cost>=0,profile.source_sheet);
  }
});

test('ordinary cabinet BOM selects material-specific prices',()=>{
  const [seccProfile,seccLines]=get('JM',1,0,'SECC');
  const [stainlessProfile,stainlessLines]=get('JM',1,0,'SUS304');
  const env={data_version:bundle.data_version,width_mm:800,height_mm:1500,depth_mm:300,spray_unit_price:26};
  const secc=calculateCabinetAuxiliary(seccProfile,seccLines,env);
  const stainless=calculateCabinetAuxiliary(stainlessProfile,stainlessLines,env);
  assert.ok(stainless.auxiliary_cost>secc.auxiliary_cost);
  assert.deepEqual(stainlessProfile.material_codes,['SUS304','SUS316']);
});

test('all 72 fixed auxiliary prices execute from the complete price workbook',()=>{
  assert.equal(bundle.fixed_rules.length,72);
  for(const rule of bundle.fixed_rules){
    for(const material_code of rule.material_codes){
      const model_code=rule.product_code==='JC_EXP'?`${rule.model_code}-${rule.profile_code==='LUXURY'?1:2}`:rule.model_code;
      const result=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{data_version:bundle.data_version,
        product_code:rule.product_code,model_code,variant_code:null,material_code,
        width_mm:rule.width_mm,height_mm:rule.height_mm,depth_mm:rule.depth_mm});
      assert.equal(result.match_method,'FIXED_EXACT',`${rule.source_sheet}!${rule.source_row_no}`);
      assert.equal(result.auxiliary_cost,Math.round(Number(rule.auxiliary_cost)*100)/100);
    }
  }
});

test('JK and JC use material and configuration specific fixed prices',()=>{
  const base={data_version:bundle.data_version,variant_code:null};
  const jk=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{...base,product_code:'JK',model_code:'',material_code:'SECC',width_mm:300,height_mm:200,depth_mm:80});
  const jkStainless=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{...base,product_code:'JK',model_code:'',material_code:'SUS316',width_mm:300,height_mm:200,depth_mm:80});
  assert.equal(jk.auxiliary_cost,8.3);assert.equal(jkStainless.auxiliary_cost,30.29);
  const luxury=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{...base,product_code:'JC_EXP',model_code:'JC601660-1',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600});
  const standard=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{...base,product_code:'JC_EXP',model_code:'JC601660-2',material_code:'SECC',width_mm:600,height_mm:1600,depth_mm:600});
  assert.equal(luxury.auxiliary_cost,652.5);assert.equal(standard.auxiliary_cost,501);
});

test('fixed auxiliary nonstandard dimensions keep the existing perimeter scaling rule',()=>{
  const result=calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{data_version:bundle.data_version,product_code:'JQ_EXP',
    model_code:'CUSTOM',variant_code:null,material_code:'SECC',width_mm:700,height_mm:960,depth_mm:480});
  assert.equal(result.match_method,'FIXED_DIMENSION_SCALE');
  assert.equal(result.reference_width_mm,800);
  assert.equal(result.auxiliary_cost,Math.round(136.7*((700+960+480)/(800+960+480))*100)/100);
});

test('wide products use only their fixed rules and do not reuse ordinary BOM',()=>{
  const [profile,lines]=get('JP',1,0);
  assert.notEqual(profile.product_code,'JP_WIDE_EXP');
  assert.equal(lines.every(line=>line.profile_key.startsWith('JP:')),true);
  assert.throws(()=>calculateCabinetAuxiliaryFixed(bundle.fixed_rules,{data_version:bundle.data_version,product_code:'JP_WIDE_EXP',
    model_code:'JP131860',variant_code:'WIDE',material_code:'SUS304',width_mm:1300,height_mm:1800,depth_mm:600}),/没有适用的最新辅材价格/);
});

test('legacy auxiliary cleanup is guarded by a complete active V2 catalog',()=>{
  const migration=fs.readFileSync(new URL('../database/migrations/cabinet_auxiliary_v2.sql',import.meta.url),'utf8');
  const cleanup=fs.readFileSync(new URL('../database/online-rollout-20260911/auxiliary-cleanup/01-delete-legacy-auxiliary.sql',import.meta.url),'utf8');
  assert.match(migration,/stage_cabinet_auxiliary_catalog_v2/);
  assert.match(migration,/fixed_rules[^]*<>72/);
  assert.match(migration,/CREATE OR REPLACE FUNCTION calc\.get_auxiliary_cost/);
  assert.match(cleanup,/v_profiles<>16 OR v_lines<>255 OR v_fixed<>72/);
  assert.match(cleanup,/DROP TABLE IF EXISTS calc\.auxiliary_experience_price/);
  assert.doesNotMatch(cleanup,/\bCASCADE\b/i);
});
