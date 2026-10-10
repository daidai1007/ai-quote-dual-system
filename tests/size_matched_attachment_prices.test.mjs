// Targeted, offline coverage: the ten non-board size-matching families.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { calculateAttachment, attachmentTotals } from '../api/attachment_cost.mjs';
import { createAttachmentService } from '../api/attachment_service.mjs';
import { round } from '../api/attachment_formula.mjs';

const names=['固定底座','活动底座','内门','玻璃门','JP控制柜侧板','分段板','固定立柱','三排安装梁','防雨顶','通风顶罩'];
const env={product_code:'JP',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:700,
  coating_type:'橘纹',quote_date:'2026-10-10',density_g_cm3:7.85,material_unit_price:4.2,spray_unit_price:26};
const manuals={底座高度:100,分段板高度:150,玻璃门宽度:705,玻璃门高度:1633,通风顶罩高度:150};
const bundle=JSON.parse(readFileSync(new URL('../database/attachment-v2/generated/attachment-bundle.json',import.meta.url)));
const items=names.map((name,index)=>({attachment_price_id:index+1,data_version:'offline',item_name:name,
  category_level1:name.includes('底座')?'底座':name.includes('侧板')?'侧板':
    ['固定立柱','三排安装梁','分段板'].includes(name)?'安装附件':'控制柜附件',category_level2:'',
  unit:'件',price:100,width_mm:600,height_mm:name.includes('底座')?80:name==='通风顶罩'?100:1600,depth_mm:500,
  rules:bundle.rules.filter(rule=>rule.item_name===name&&rule.category_level1!== '控制箱附件')}));

function target(item,environment=env,manual=manuals) {
  return [environment.width_mm,item.item_name.includes('底座')?manual.底座高度:
    item.item_name==='通风顶罩'?manual.通风顶罩高度:environment.height_mm,environment.depth_mm];
}

test('ten families: exact catalogue price, nearest-size scaled amount, quantity, and actual-dimension costs',()=>{
  for (const item of items) {
    const selection={quantity:3,manual_inputs:manuals,unit_price_override:1,size_match_ratio:999};
    const row=calculateAttachment(selection,item,item.rules,env);
    const dimensions=target(item);
    const ratio=dimensions.reduce((a,b)=>a+b,0)/(item.width_mm+item.height_mm+item.depth_mm);
    assert.equal(row.status,'CALCULATED',item.item_name+': '+row.error);
    assert.equal(row.unit_price_override,round(100*ratio,6),item.item_name);
    assert.equal(row.quick_amount,round(row.unit_price_override*3));
    assert.equal(row.catalogue_quick_amount,300);
    const exact=calculateAttachment(selection,{...item,width_mm:dimensions[0],height_mm:dimensions[1],depth_mm:dimensions[2]},item.rules,env);
    assert.equal(exact.quick_amount,300);
    assert.equal(exact.unit_price_override,undefined);
    assert.equal(row.formula_unit_cost,exact.formula_unit_cost,'Matched catalogue sizes must not affect costs: '+item.item_name);
    assert.equal(row.formula_amount,exact.formula_amount);
    assert.equal(row.formula_amount,round(row.formula_unit_cost*3));
  }
});

test('missing dimensions are completed for matching only; beam depth is decoded from its model',()=>{
  const side=calculateAttachment({quantity:2},{...items[4],width_mm:null},[],env);
  assert.equal(side.width_mm,null);
  assert.equal(side.size_match_width_mm,800);
  assert.equal(side.unit_price_override,round(100*3300/2900,6));
  const beam=calculateAttachment({quantity:2},{...items[7],width_mm:null,height_mm:null,depth_mm:null,model_code:'JP760260'},[],env);
  assert.equal(beam.depth_mm,null);
  assert.equal(beam.size_match_depth_mm,600);
  assert.equal(beam.unit_price_override,103.125);
  assert.equal(beam.quick_amount,206.25);
  assert.equal(calculateAttachment({quantity:1},{...items[0],item_name:'风机',category_level1:'风机'},[],env).quick_amount,100);
  assert.equal(calculateAttachment({quantity:1,attachment_price_sign:-1},items[0],[],env).status,'ERROR');
});

test('real preview uses each child cabinet; snapshot and export keep effective prices without changing catalogue audit amounts',async()=>{
  let saved,sqlWritten;
  const service=createAttachmentService({env:{},calculateBase:async()=>({
    quick_quote:{attachment_fee:0,total_cost:1000},formula_cost:{attachment_fee:0,total_cost:500}}),
    runPsql:async sql=>{
      if(sql.includes('attachment_catalog_version')) return JSON.stringify([{data_version:'offline',status:'ACTIVE'}]);
      if(sql.includes('FROM (SELECT p.attachment_price_id')) return JSON.stringify(items);
      if(sql.includes('density_g_cm3')) return JSON.stringify({density_g_cm3:7.85,spray_unit_price:26});
      if(sql.startsWith('BEGIN;')) {
        sqlWritten=sql;
        const objects=[...sql.matchAll(/decode\('([0-9a-f]+)','hex'\)/g)]
          .map(match=>Buffer.from(match[1],'hex').toString('utf8')).filter(value=>value.startsWith('{')).map(JSON.parse);
        saved={environment:objects.find(value=>value.quote_result),attachments:objects.filter(value=>value.catalogue_quick_amount!==undefined)};
        return JSON.stringify(saved);
      }
      if(sql.includes('FROM calc.attachment_quote_line l')) return JSON.stringify(saved);
      throw new Error('Unexpected offline SQL');
    }});
  const children=[{width_mm:800,height_mm:1800,depth_mm:700},{width_mm:600,height_mm:1800,depth_mm:500}];
  const attachments=items.map(item=>({attachment_price_id:item.attachment_price_id,quantity:2,manual_inputs:manuals}));
  const input={...env,quote_id:'offline',material_unit_price_override:4.2,attachments};
  const result=await service.calculate(input);
  const fee=attachmentTotals(result.attachments).quick_attachment_fee;
  assert.equal(result.quick_quote.total_cost,round(1000+fee));
  for (const row of result.attachments) assert.equal(row.catalogue_quick_amount,200);
  assert.equal((sqlWritten.match(/,100,200,/g)||[]).length,10);
  const hydrated=await service.hydrateDocument({items:[{...input,attachment_contract:2,
    quote_line_id:result.quote_line_id,quantity:4}]});
  assert.deepEqual(hydrated.items[0].attachments,result.attachments);
  assert.equal(hydrated.items[0].quick.total_cost,result.quick_quote.total_cost);
  const childRows=[0,1].flatMap(index=>[items[0],items[2],items[3]].map(item=>({
    attachment_price_id:item.attachment_price_id,quantity:1,manual_inputs:manuals,ganged_cabinet_index:index})));
  const preview=await service.preview({...input,attachments:childRows,ganged_cabinet_count:2,
    ganged_cabinets:children,ganged_cabinet_inputs:children});
  for (const row of preview.attachments) {
    const child=children[row.ganged_cabinet_index];
    const item=items.find(value=>value.attachment_price_id===row.attachment_price_id);
    const expected=calculateAttachment({...row,manual_inputs:manuals},item,item.rules,{...env,...child});
    assert.equal(row.quick_amount,expected.quick_amount);
    assert.equal(row.formula_amount,expected.formula_amount);
  }
  assert.notEqual(preview.attachments[0].quick_amount,preview.attachments[3].quick_amount);
  assert.notEqual(preview.attachments[1].formula_amount,preview.attachments[4].formula_amount);
});
