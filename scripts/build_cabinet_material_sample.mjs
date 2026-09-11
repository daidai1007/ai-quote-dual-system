import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

import {applyCabinetMaterial,calculateCabinetMaterial} from '../api/cabinet_material_service.mjs';
import {applyCabinetSpray,calculateCabinetSpray} from '../api/cabinet_spray_service.mjs';
import {applyCabinetAuxiliary,calculateCabinetAuxiliary} from '../api/cabinet_auxiliary_service.mjs';
import {applyCabinetLabor,calculateCabinetLabor} from '../api/cabinet_labor_service.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const bundle=JSON.parse(fs.readFileSync(path.join(root,'database/cabinet-material/generated/cabinet-material-bundle.json')));
const sprayBundle=JSON.parse(fs.readFileSync(path.join(root,'database/cabinet-spray/generated/cabinet-spray-bundle.json')));
const auxiliaryBundle=JSON.parse(fs.readFileSync(path.join(root,'database/cabinet-auxiliary/generated/cabinet-auxiliary-bundle.json')));
const laborBundle=JSON.parse(fs.readFileSync(path.join(root,'database/cabinet-labor/generated/cabinet-labor-bundle.json')));
const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/export_formula_cost_detail.json')));
const outputDir=path.join(root,'test-output/cabinet-material-v1');fs.mkdirSync(outputDir,{recursive:true});
const materials=[{material_code:'SECC',density_g_cm3:7.85,material_unit_price:5},{material_code:'SUS304',density_g_cm3:7.93,material_unit_price:20}];
const base=fixture.items[0];
fixture.quote_no='LOCAL-CABINET-MATERIAL-V1';
fixture.items=[
  {material_code:'SECC',waste_factor:1.2,name:'JS 本地验证 SECC',quote_id:'LOCAL-JS-SECC'},
  {material_code:'SUS304',waste_factor:1.3,name:'JS 本地验证 SUS304（含固定SECC零件）',quote_id:'LOCAL-JS-SUS304'},
].map((sample,index)=>{
  const environment={data_version:bundle.data_version,product_code:'JS',width_mm:1000,height_mm:1800,depth_mm:600,
    single_door_count:1,double_door_count:0,cabinet_body_thickness_mm:1.5,materials,
    coating_type:'平光',spray_unit_price:30,management_fee_rate:.13,...sample};
  const material=calculateCabinetMaterial(bundle.rules,environment);
  const spray=calculateCabinetSpray(sprayBundle.rules,{...environment,data_version:sprayBundle.data_version});
  const auxiliaryProfile=auxiliaryBundle.profiles.find(profile=>profile.product_code==='JS'&&profile.single_door_count===1&&profile.double_door_count===0);
  const auxiliary=calculateCabinetAuxiliary(auxiliaryProfile,
    auxiliaryBundle.lines.filter(line=>line.profile_key===auxiliaryProfile.profile_key),
    {...environment,data_version:auxiliaryBundle.data_version});
  const labor=calculateCabinetLabor(laborBundle.rules,{...environment,data_version:laborBundle.data_version},material);
  let result=applyCabinetMaterial({formula_cost:{...base.formula},quick_quote:{...base.quick}},material);
  result=applyCabinetSpray(result,spray);
  result=applyCabinetAuxiliary(result,auxiliary);
  result=applyCabinetLabor(result,labor);
  return {...structuredClone(base),...sample,source_pdf_name:`本地验证-${index+1}.pdf`,product_code:'JS',product_family:'JS',
    width_mm:1000,height_mm:1800,depth_mm:600,single_door_count:1,double_door_count:0,
    cabinet_body_thickness_mm:1.5,formula:result.formula_cost,quick:result.quick_quote,
    notes:'本地验证样例；材料单价为测试值，不作为线上报价依据。',final_remark:'本地验证样例；材料单价为测试值，不作为线上报价依据。'};
});
const input=path.join(outputDir,'代表性公式法导出-输入.json');
const output=path.join(outputDir,'代表性公式法导出.xlsx');
fs.writeFileSync(input,JSON.stringify(fixture,null,2));
const run=spawnSync(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,stdio:'inherit'});
if(run.status!==0)process.exit(run.status??1);
console.log(JSON.stringify({output,items:fixture.items.map(item=>({name:item.name,material:item.material_code,
  waste_factor:item.formula.waste_factor,net_weight_kg:item.formula.net_material_weight_kg,
  billable_weight_kg:item.formula.corrected_material_weight_kg,material_cost:item.formula.material_cost,
  spray_cost:item.formula.spray_cost,auxiliary_cost:item.formula.auxiliary_cost,
  labor_cost:item.formula.labor_cost,management_fee:item.formula.management_fee}))},null,2));
