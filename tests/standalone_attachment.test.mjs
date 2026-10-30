import test from 'node:test';
import assert from 'node:assert/strict';
import {calculateStandaloneAttachment as evaluate,assertStandaloneReady} from '../api/standalone_attachment.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown} from '../quick_discount_rules.mjs';

const fixed={attachment_price_id:1,item_name:'门锁',category_level1:'控制柜附件',unit:'把',price:30,data_version:'v1',rules:[{rule_id:1,data_version:'v1',method:'FIXED',fixed_cost:18,products:[],materials:[]}]};
const formula={attachment_price_id:2,item_name:'安装板',category_level1:'安装板',unit:'块',price:200,data_version:'v1',width_mm:800,height_mm:600,
 rules:[{rule_id:2,data_version:'v1',method:'CALCULATED',products:['JP'],materials:['SECC'],formulas:{weight_kg:'宽度*高度*1.5*材质密度*0.000001',material_cost:'材料重量*材质单价',spray_area_m2:'宽度*高度*2*0.000001',spray_cost:'喷塑面积*喷塑单价',auxiliary_cost:'0',labor_cost:'18'}}]};
const settings={carbon_price:4.2,galvanized_price:4.2,surface_price:26,stainless_304_price:16,stainless_316_price:32.4};
const data={items:[fixed,formula],data_version:'v1',material_densities:{SECC:7.85,SGCC:7.85,SUS304:7.93,SUS316:7.98}};
const calculate=(source,entries)=>evaluate({standalone_cost_settings:settings,...source},entries);
const own={材质密度:7.85,材质单价:4.2,喷塑单价:26};

test('fixed attachment quotes without any cabinet dimensions or material',()=>{
 const row=calculate({item_name:'门锁',quantity:1,width_mm:9999,height_mm:8888,depth_mm:7777},data);
 assertStandaloneReady(row);assert.equal(row.formula_amount,18);assert.equal(row.quick_amount,30);
 assert.equal(row.standalone_environment.width_mm,undefined);assert.equal(row.unit,'把');
});
test('formula uses explicit catalogue axes and explicit own material inputs',()=>{
 const row=calculate({attachment_price_id:2,manual_inputs:own},data);
 assertStandaloneReady(row);assert.equal(row.standalone_environment.width_mm,800);
 assert.equal(row.weight_kg,5.652);assert.equal(row.formula_amount,66.7);
 assert.equal(row.standalone_material_code,'SGCC');
});
test('missing prices and dimensions stay pending, with null amounts',()=>{
 const pending=calculate({attachment_price_id:2},{...data,items:[{...formula,width_mm:null}]});
 assert.deepEqual(pending.pending_manual_dimensions,['宽度']);
 assert.equal(pending.formula_amount,null);assert.equal(pending.quick_amount,null);
 assert.throws(()=>assertStandaloneReady(pending),/完善/);
 const missing=calculate({attachment_price_id:2,manual_inputs:own},{...data,items:[{...formula,width_mm:null}]});
 assert.deepEqual(missing.pending_manual_dimensions,['宽度']);
 assert.throws(()=>calculate({attachment_price_id:2,standalone_cost_settings:{}},data),/修改系数/);
});
test('user dimensions override catalogue dimensions and a zero coating price is explicit',()=>{
 const row=calculate({attachment_price_id:2,standalone_cost_settings:{...settings,surface_price:0},manual_inputs:{...own,宽度:1200,喷塑单价:999,材质单价:999,材质密度:999}},data);
 assertStandaloneReady(row);assert.equal(row.standalone_environment.width_mm,1200);
 assert.equal(row.spray_cost,0);assert.equal(row.weight_kg,8.478);
 assert.equal(row.standalone_environment.material_unit_price,4.2);
 assert.equal(calculate({attachment_price_id:2,manual_inputs:{...own,宽度:-10}},data).status,'PENDING_MANUAL');
});
test('all names containing 安装板 use galvanized coefficients, even if stainless was selected',()=>{
 for(const item_name of ['安装板','JK安装板','填充安装板','安装板单发']){
  const selected={...formula,item_name};
  const row=calculate({attachment_price_id:2,standalone_material_code:'SUS304',standalone_cost_settings:{...settings,galvanized_price:7,carbon_price:99}}, {...data,items:[selected]});
  assertStandaloneReady(row);assert.equal(row.standalone_material_code,'SGCC');
  assert.equal(row.standalone_environment.material_unit_price,7);
  assert.equal(row.material_cost,39.56);
 }
});
test('duplicate names require catalogue selection; no arbitrary model or first rule',()=>{
 const extra={...formula,attachment_price_id:3,width_mm:1000};
 const row=calculate({item_name:'安装板'}, {...data,items:[formula,extra]});
 assert.deepEqual(row.pending_manual_dimensions,['目录规格']);assert.equal(row.standalone_parameter_choices.目录规格.length,2);
 const conflicts=calculate({attachment_price_id:2},{...data,items:[{...formula,rules:[...formula.rules,{...formula.rules[0],rule_id:3,products:['JS']}]}]});
 assert.deepEqual(conflicts.pending_manual_dimensions,['适用柜型']);
});
test('manual selling price survives repricing while missing cost cannot be zero-filled',()=>{
 const row=calculate({attachment_price_id:1,custom_amount_edited:true,unit_price_override:42.25},data);
 assert.equal(row.quick_amount,42.25);assert.equal(row.formula_amount,18);
 const noRule={...fixed,rules:[]};
 assert.deepEqual(calculate({attachment_price_id:1},{...data,items:[noRule]}).pending_manual_dimensions,['成本单价']);
 assert.equal(calculate({attachment_price_id:1,manual_inputs:{成本单价:0}},{...data,items:[noRule]}).formula_amount,0);
 assert.throws(()=>calculate({attachment_price_id:1,quantity:2},data),/内部数量/);
});
test('manual independent attachment has explicit cost and face inputs',()=>{
 const row=calculate({custom:true,item_name:'非标连接件',manual_inputs:{成本单价:12.5,面价单价:20}},data);
 assertStandaloneReady(row);assert.equal(row.formula_amount,12.5);assert.equal(row.quick_amount,20);
 assert.equal(calculate({custom:true,item_name:'临时件'},data).status,'PENDING_MANUAL');
 assert.equal(calculate({...row,custom_cost_edited:true,formula_unit_cost_override:15},data).formula_amount,15);
});
test('confirmation validates cost/quantity/unit with read-only SQL and historical catalogue version',async()=>{
 const row=calculate({attachment_price_id:1},data),sql=[];
 const service=createAttachmentService({calculateBase:()=>{throw Error('must not calculate a cabinet');},
   runPsql:async query=>{sql.push(query);return JSON.stringify(query.includes('FROM calc.material')?data.material_densities:[fixed]);}});
 const item={item_type:'standalone_attachment',product_code:'standalone_attachment',attachment_contract:'standalone_v1',
   attachments:[row],unit:'把',quantity:3,quick_discount:.85,freight_fee:0,pricing_basis:PRICING_BASIS,scheme2_cost_settings:settings,
   quick:{base_price:0,attachment_fee:30,total_cost:30}};
 const line=quickOrderLineBreakdown({quote:item.quick,attachments:[row],discount:.85,cabinetQuantity:3,freightFee:0});
 item.quote_display={name:'门锁',specification:'—',unit:'把',quantity:3,discount:.85,unit_price:line.equivalentUnitTotal,total:line.lineTotal,
   attachment_face_price:30,material_difference:0,quick_base_price:0,quick_attachment_fee:30,quick_total_cost:30,attachments:[row]};
 const hydrated=await service.hydrateDocument({items:[item]});
 assert.equal(hydrated.items[0].quick.base_price,0);assert.equal(hydrated.items[0].formula.attachment_fee,18);
 assert(sql.every(query=>!/(INSERT|UPDATE|DELETE|ALTER|CREATE)\s/i.test(query)));
 await assert.rejects(service.hydrateDocument({items:[{...item,unit:'台'}]}),/单位/);
 await assert.rejects(service.hydrateDocument({items:[{...item,attachments:[{...row,formula_amount:0}]}]}),/金额/);
});
