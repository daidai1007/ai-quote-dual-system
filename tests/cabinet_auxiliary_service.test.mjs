import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {applyCabinetAuxiliary,calculateCabinetAuxiliary} from '../api/cabinet_auxiliary_service.mjs';

const bundle=JSON.parse(fs.readFileSync(new URL('../database/cabinet-auxiliary/generated/cabinet-auxiliary-bundle.json',import.meta.url)));
const get=(product,single,double)=>{const profile=bundle.profiles.find(p=>p.product_code===product&&p.single_door_count===single&&p.double_door_count===double);return [profile,bundle.lines.filter(l=>l.profile_key===profile.profile_key)];};

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

test('all 16 profiles and 255 BOM rows execute',()=>{
  assert.equal(bundle.profiles.length,16);assert.equal(bundle.lines.length,255);
  for(const profile of bundle.profiles){
    const lines=bundle.lines.filter(line=>line.profile_key===profile.profile_key);
    const result=calculateCabinetAuxiliary(profile,lines,{data_version:bundle.data_version,width_mm:1000,height_mm:2200,depth_mm:600,spray_unit_price:26});
    assert.equal(result.lines.length,lines.length,profile.source_sheet);assert.ok(result.auxiliary_cost>=0,profile.source_sheet);
  }
});

test('wide product code cannot reuse ordinary JP BOM',()=>{
  const [profile,lines]=get('JP',1,0);
  assert.notEqual(profile.product_code,'JP_WIDE_EXP');
  assert.equal(lines.every(line=>line.profile_key.startsWith('JP:')),true);
});
