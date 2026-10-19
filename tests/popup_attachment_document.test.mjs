import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {promisify} from 'node:util';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown,moneySum} from '../quick_discount_rules.mjs';

const lineId='11111111-1111-4111-8111-111111111111';
const environment={product_code:'JP_SINGLE',material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,
  coating_type:'橘纹',quote_date:'2026-10-16',ganged_cabinet_count:1,ganged_cabinets:[],quote_result:{
    formula_cost:{material_cost:60,auxiliary_cost:10,labor_cost:0,management_fee:0,spray_cost:10,
      total_cost:100,attachment_fee:20},quick_quote:{base_price:500,total_cost:550,attachment_fee:50}}};
const old={attachment_price_id:1,item_name:'旧附件',quantity:1,manual_inputs:{},status:'ERROR',
  formula_amount:null,quick_amount:50,error:'旧快照缺少尺寸'};
const fan={attachment_price_id:9,item_name:'风机SG22060HA2/220V（国产）',quantity:4,
  attachment_price_sign:1,manual_inputs:{},category_level1:'风机',catalog_version:'popup-catalog',
  status:'FIXED',formula_unit_cost:70,formula_amount:280,quick_amount:480,
  quick_amount_override:480,custom_amount_edited:true};

function quote(rows=[fan],quantity=2){
  const attachments=structuredClone(rows);
  const quick={base_price:500,attachment_fee:moneySum(rows.map(row=>row.quick_amount)),
    total_cost:moneySum([500,...rows.map(row=>row.quick_amount)])};
  const item={...structuredClone(environment),name:'弹窗报价',specification:'800*600*1800',
    quantity,quick_discount:0.5,formula_discount:1,freight_fee:70,
    attachment_contract:2,quote_line_id:lineId,pricing_basis:PRICING_BASIS,attachments,quick};
  const line=quickOrderLineBreakdown({quote:quick,attachments,discount:0.5,cabinetQuantity:quantity,freightFee:70});
  item.quote_display={attachment_source:'popup_v1',attachments:structuredClone(attachments),
    name:item.name,specification:item.specification,unit:'台',quantity,discount:0.5,
    unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:line.attachmentFee,
    material_difference:0,quick_base_price:500,quick_attachment_fee:quick.attachment_fee,
    quick_total_cost:quick.total_cost,remark:'弹窗冻结测试'};
  return item;
}
function harness(savedEnvironment=environment){
  const queries=[];
  const service=createAttachmentService({env:{},runPsql:async sql=>{
    queries.push(sql);
    assert.doesNotMatch(sql,/\b(?:INSERT|UPDATE|DELETE|COMMIT|BEGIN)\b|calc\.attachment_price\b|calc\.attachment_cost_rule\b|calc\.attachment_selection\b/);
    return JSON.stringify({[lineId]:{environment:savedEnvironment,attachments:[old]}});
  }});
  return {service,queries};
}

test('current popup model, quantity, manual sale and cost replace old attachment rows without repricing',async()=>{
  const h=harness(),input=quote();
  const {items:[item]}=await h.service.hydrateDocument({items:[input]});
  assert.equal(h.queries.length,1);
  assert.deepEqual(item.attachments,input.quote_display.attachments);
  assert.equal(item.formula.attachment_fee,280);
  assert.equal(item.formula.management_fee_base,430);
  assert.equal(item.formula.management_fee,25.8);
  assert.equal(item.formula.total_cost,385.8);
  assert.equal(item.quick.total_cost,980);
  assert.equal(item.quote_line_id,lineId);
  assert.equal(old.status,'ERROR');
});

test('manual zero, custom costs, quick-only rows and negative installation board retain their popup values',async()=>{
  const zero={...fan,quick_amount:0,quick_amount_override:0};
  const custom={custom:true,item_name:'人工附件',quantity:1,formula_amount:12,quick_amount:15};
  const quickOnly={...fan,attachment_price_id:10,item_name:'柜门改造',status:'QUICK_ONLY',
    formula_amount:null,quick_amount:100,quick_amount_override:100};
  const deduction={...fan,attachment_price_id:11,item_name:'安装板',category_level1:'安装板',
    quantity:2,attachment_price_sign:-1,formula_amount:-20,quick_amount:-30,quick_amount_override:-30};
  const h=harness();
  const {items:[item]}=await h.service.hydrateDocument({items:[quote([zero,custom,quickOnly,deduction])]});
  assert.deepEqual(item.attachments.map(row=>row.quick_amount),[0,15,100,-30]);
  assert.deepEqual(item.attachments.map(row=>row.formula_amount),[280,12,0,-20]);
  assert.equal(item.formula.attachment_fee,272);
  assert.equal(item.quick.attachment_fee,85);
});

test('ganged and ordinary quotes use the same popup source and scale only by order quantity',async()=>{
  const children=[{width_mm:800,depth_mm:600,height_mm:1800},{width_mm:600,depth_mm:600,height_mm:1800}];
  const gangedEnvironment={...structuredClone(environment),ganged_cabinet_count:2,ganged_cabinets:children};
  const rows=[{...fan,ganged_cabinet_index:0},{...fan,attachment_price_id:12,ganged_cabinet_index:1,
    item_name:'风机另一型号',quantity:2,formula_amount:90,quick_amount:120,quick_amount_override:120}];
  const inputs=[1,10].map(quantity=>({...quote(rows,quantity),ganged_cabinet_count:2,ganged_cabinets:children}));
  const h=harness(gangedEnvironment);
  const {items}=await h.service.hydrateDocument({items:inputs});
  assert.equal(h.queries.length,1);
  assert.deepEqual(items[0].attachments.map(row=>row.ganged_cabinet_index),[0,1]);
  assert.equal(items[0].formula.attachment_fee,370);
  assert.equal(items[0].quick.attachment_fee,600);
  assert.equal(items[1].quote_display.unit_price,items[0].quote_display.unit_price);
  assert.equal(items[1].quote_display.total,items[0].quote_display.total*10);
  assert.equal(items[1].quick.attachment_fee,600);
});

test('incomplete popup cost, inconsistent totals and changed cabinet dimensions are rejected',async()=>{
  const h=harness();
  const pending=quote();pending.quote_display.attachments[0].status='PENDING_MANUAL';
  await assert.rejects(h.service.hydrateDocument({items:[pending]}),/成本或尺寸未完成/);
  const missing=quote();missing.quote_display.attachments[0].formula_amount=null;
  await assert.rejects(h.service.hydrateDocument({items:[missing]}),/附件成本无效/);
  const wrong=quote();wrong.quote_display.total+=1;
  await assert.rejects(h.service.hydrateDocument({items:[wrong]}),/报价金额不一致/);
  const changed=quote();changed.height_mm=1900;
  await assert.rejects(h.service.hydrateDocument({items:[changed]}),/height_mm/);
});

test('JE missing old management and totals uses confirmed costs and six percent including freight',async()=>{
  for(const count of [1,2]) {
    const saved=structuredClone(environment);
    saved.ganged_cabinet_count=count;
    saved.ganged_cabinets=count===1?[]:[{width_mm:740},{width_mm:740}];
    saved.quote_result.formula_cost={material_cost:826.52,auxiliary_cost:49.60,labor_cost:332.54,
      spray_cost:80.65,attachment_fee:null,management_fee:null,total_cost:null,management_fee_rate:.13};
    const original=structuredClone(saved);
    const rows=[{...fan,formula_amount:720.88,quick_amount:1562,quick_amount_override:1562}];
    const input={...quote(rows,10),freight_fee:61.86,ganged_cabinet_count:count,ganged_cabinets:saved.ganged_cabinets};
    const line=quickOrderLineBreakdown({quote:input.quick,attachments:rows,discount:.5,cabinetQuantity:10,freightFee:61.86});
    Object.assign(input.quote_display,{unit_price:line.equivalentUnitTotal,total:line.lineTotal});
    const {items:[item]}=await harness(saved).service.hydrateDocument({items:[input]});
    assert.equal(item.formula.management_fee,124.32);
    assert.equal(item.formula.management_fee_rate,.06);
    assert.equal(item.formula_base.management_fee_rate,.06);
    assert.equal(item.formula_base.management_fee,124.32);
    assert.equal(item.formula.total_cost,2134.51);
    assert.equal(moneySum([item.formula.total_cost,input.freight_fee]),2196.37);
    assert.equal(item.formula.attachment_fee,720.88);
    assert.deepEqual(saved,original,'original partial snapshot is not rewritten');
    assert.deepEqual(item.attachments[0].quick_amount_override,1562);
  }
});

test('obsolete fees cannot affect output and missing source costs cannot use a stored total',async()=>{
  const saved=structuredClone(environment);
  saved.quote_result.formula_cost.management_fee=999999;
  saved.quote_result.formula_cost.total_cost=9999999;
  const result=await harness(saved).service.hydrateDocument({items:[quote()]});
  assert.equal(result.items[0].formula.management_fee,25.8);
  delete saved.quote_result.formula_cost.auxiliary_cost;
  await assert.rejects(harness(saved).service.hydrateDocument({items:[quote()]}),/缺少辅材成本/);
});

test('actual ordinary and ganged workbooks preserve popup fan sale and formula cost',async()=>{
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'popup-document-'));
  try{
    for(const count of [1,2]){
      const item=quote(),savedEnvironment=structuredClone(environment);
      if(count===2){
        const children=[{width_mm:800,depth_mm:600,height_mm:1800},{width_mm:600,depth_mm:600,height_mm:1800}];
        Object.assign(item,{ganged_cabinet_count:2,ganged_cabinets:children});
        Object.assign(savedEnvironment,{ganged_cabinet_count:2,ganged_cabinets:children});
        item.attachments[0].ganged_cabinet_index=0;
        item.quote_display.attachments[0].ganged_cabinet_index=0;
      }
      const payload=await harness(savedEnvironment).service.hydrateDocument({quote_id:'POPUP-SNAPSHOT-TEST',
        quote_date:'2026-10-16',company_name:'快照验证公司',items:[item]});
      const input=path.join(folder,`input-${count}.json`),output=path.join(folder,`quote-${count}.xlsx`);
      await fs.writeFile(input,JSON.stringify(payload));
      await promisify(execFile)(process.execPath,[path.resolve('export_dual_quote_workbook.mjs'),input,output],{windowsHide:true});
      const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
      for(const [sheet,amount] of [['快速报价单',480],['公式法报价单',280]]){
        const table=book.getWorksheet(sheet),column=table.getRow(10).values.findIndex(value=>value===fan.item_name);
        assert.ok(column>0,`${sheet} missing fan column`);
        assert.equal(table.getCell(11,column).value,amount);
      }
      const quick=book.getWorksheet('快速报价单');
      assert.equal(quick.getCell('F11').value,payload.items[0].quote_display.unit_price);
      assert.equal(quick.getCell('G11').value,payload.items[0].quote_display.total);
      const formula=book.getWorksheet('公式法报价单');
      assert.equal(formula.getCell('F11').value,455.8);
      assert.equal(formula.getCell('G11').value,911.6);
      const details=book.getWorksheet('成本明细');
      const management=[];
      details.eachRow(row=>{if(row.getCell(4).value==='管理费用') management.push(row);});
      assert.equal(management.length,1,'whole-set management is only listed once');
      assert.match(management[0].getCell(6).value,/运费的 6%/);
      assert.equal(management[0].getCell(8).value,430);
      assert.equal(management[0].getCell(10).value,.06);
      assert.equal(management[0].getCell(11).value,25.8);
      assert.equal(management[0].getCell(13).value,51.6);
      const audit=book.getWorksheet('附件双报价明细');
      assert.equal(audit.getCell('B2').value,null,'must not invent a database attachment-selection ID');
      assert.equal(audit.getCell('AF2').value,'当前附件弹窗确认快照');
      assert.equal(audit.getCell('AG2').value,9);
      assert.equal(audit.getCell('AH2').value,count===2?1:null);
      if(process.env.AI_QUOTE_KEEP_POPUP_TEST_ARTIFACTS==='1'){
        await fs.copyFile(output,path.resolve(`outputs/popup-snapshot-${count}-cabinet.xlsx`));
      }
    }
  }finally{await fs.rm(folder,{recursive:true,force:true});}
});
