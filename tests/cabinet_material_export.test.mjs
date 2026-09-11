import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';

const root=path.resolve(import.meta.dirname,'..');
const run=(input,output)=>new Promise((resolve,reject)=>{
  const child=spawn(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,windowsHide:true});
  let stderr='';child.stderr.on('data',chunk=>stderr+=chunk);
  child.once('error',reject);child.once('close',code=>code===0?resolve():reject(new Error(stderr||`export exited ${code}`)));
});

test('workbook exports cabinet material and spray calculations per part',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'cabinet-material-export-'));
  try{
    const payload=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/export_formula_cost_detail.json'),'utf8'));
    const item=payload.items[0];
    item.formula.material_cost=123.45;
    item.formula.net_material_weight_kg=20;
    item.formula.corrected_material_weight_kg=24;
    item.formula.waste_factor=1.2;
    item.formula.cabinet_material_version='cabinet-material-test-v1';
    item.formula.cabinet_material_part_details=[{
      part_name:'安装板',material_code:'SECC',fixed_material_code:'SECC',area_m2:1.5,
      sheet_thickness_mm:2.5,internal_quantity:1,density_g_cm3:7.85,net_weight_kg:29.4375,
      waste_factor:1.2,billable_weight_kg:35.325,material_unit_price:5,material_cost:176.625,
      area_formula:'(高度-72)*(宽度-26.6)*0.000001',source_sheet:'JS',source_row_no:5,
    }];
    item.formula.product_area_m2=2;
    item.formula.spray_unit_price=12;
    item.formula.spray_cost=24;
    item.formula.cabinet_spray_version='cabinet-spray-test-v1';
    item.formula.cabinet_spray_part_details=[{
      part_name:'左右侧板-1',area_per_piece_m2:1,internal_quantity:2,total_area_m2:2,
      area_formula:'(宽度+50.5)*(深度+64)*0.000001',source_sheet:'JS',source_row_no:3,
    }];
    item.formula.auxiliary_cost=17.94;
    item.formula.cabinet_auxiliary_version='cabinet-auxiliary-test-v1';
    item.formula.cabinet_auxiliary_lines=[{
      item_name:'门框型材',material_name:'铝型材',internal_quantity:2,unit:'米',unit_price:4,
      length_per_piece_m:1.5,length_formula:'高度*0.001',base_cost:12,
      spray_area_m2:.594,spray_unit_price:10,spray_cost:5.94,line_total:17.94,
      source_sheet:'JP1',source_row_no:3,
    }];
    item.formula.labor_cost=321.45;
    item.formula.cabinet_labor_version='cabinet-labor-test-v1';
    item.formula.labor_method='LINEAR_WEIGHT';
    item.formula.labor_billable_weight_kg=55.5;
    item.formula.labor_source_formula='283.3905+0.367734*计价材料重量';
    item.formula.labor_source_sheet='JS';
    item.formula.labor_source_row_no=3;
    item.formula.labor_excluded_part_names=['安装板'];
    item.formula.management_fee_rate=.13;
    item.formula.management_fee=41.79;
    const input=path.join(dir,'input.json'),output=path.join(dir,'output.xlsx');
    await fs.writeFile(input,JSON.stringify(payload),'utf8');await run(input,output);
    const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(output);
    const sheet=workbook.getWorksheet('成本明细');
    const rows=[];sheet.eachRow(row=>rows.push(row.values.slice(1).map(value=>String(value??''))));
    const part=rows.find(row=>row.includes('安装板'));
    assert.ok(part,'missing cabinet material part row');
    assert.ok(part.some(value=>value.includes('净重 29.437500 kg')));
    assert.ok(part.some(value=>value.includes('废料系数 1.200')));
    assert.ok(part.some(value=>value.includes('cabinet-material-test-v1')));
    assert.ok(part.some(value=>value.includes('面积公式：')));
    const sprayPart=rows.find(row=>row.includes('左右侧板-1'));
    assert.ok(sprayPart,'missing cabinet spray part row');
    assert.ok(sprayPart.some(value=>value.includes('1.00000000 m²/件 × 2 件 × 12.0000 元/m² = 24.00 元')));
    assert.ok(sprayPart.some(value=>value.includes('cabinet-spray-test-v1')));
    const auxiliaryPart=rows.find(row=>row.includes('门框型材'));
    assert.ok(auxiliaryPart,'missing cabinet auxiliary BOM row');
    assert.ok(auxiliaryPart.some(value=>value.includes('1.5 m/件 × 2 件 × 4.0000 元/m')));
    assert.ok(auxiliaryPart.some(value=>value.includes('喷塑 0.594 m² × 10.0000 元/m²')));
    assert.ok(auxiliaryPart.some(value=>value.includes('cabinet-auxiliary-test-v1')));
    assert.ok(auxiliaryPart.some(value=>value.includes('长度公式：高度*0.001')));
    const laborPart=rows.find(row=>row.includes('柜体人工成本'));
    assert.ok(laborPart,'missing cabinet labor row');
    assert.ok(laborPart.some(value=>value.includes('计人工重量 55.500000 kg')));
    assert.ok(laborPart.some(value=>value.includes('cabinet-labor-test-v1')));
    assert.ok(laborPart.some(value=>value.includes('计人工重量已扣除：安装板')));
  } finally {await fs.rm(dir,{recursive:true,force:true});}
});
