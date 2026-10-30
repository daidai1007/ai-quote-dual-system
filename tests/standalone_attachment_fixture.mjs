import {readFileSync} from 'node:fs';
import {calculateStandaloneAttachment} from '../api/standalone_attachment.mjs';
const rule={rule_id:2,data_version:'offline-v1',method:'CALCULATED',products:['JP'],materials:['SECC'],formulas:{weight_kg:'宽度*高度*1.5*材质密度*0.000001',material_cost:'材料重量*材质单价',spray_area_m2:'宽度*高度*2*0.000001',spray_cost:'喷塑面积*喷塑单价',auxiliary_cost:'0',labor_cost:'18'}};
export const fixture={data_version:'offline-v1',material_densities:{SECC:7.85,SGCC:7.85,SUS304:7.93,SUS316:7.98},items:[
 {attachment_price_id:1,item_name:'门限位器',category_level1:'控制柜附件',unit:'件',price:30,data_version:'offline-v1',rules:[{rule_id:1,data_version:'offline-v1',method:'FIXED',fixed_cost:18,products:[],materials:[]}]},
 {attachment_price_id:2,item_name:'安装板',category_level1:'安装板',unit:'块',price:200,data_version:'offline-v1',width_mm:800,height_mm:600,rules:[rule]},
 {attachment_price_id:3,item_name:'安装板',category_level1:'安装板',unit:'块',price:250,data_version:'offline-v1',width_mm:1000,height_mm:800,rules:[rule]},
]};
if(process.argv[1]?.endsWith('standalone_attachment_fixture.mjs')){
 const input=JSON.parse(readFileSync(0,'utf8'));
 console.log(JSON.stringify({attachments:input.attachments.map(row=>calculateStandaloneAttachment(row,fixture))}));
}
