import {quickQuotationAmount} from './quotation_layout_reader.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,mkdir,rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import ExcelJS from '@excel.js/exceljs';
import {MANUFACTURING_COST_BASIS,manufacturingFormulaForItem,applyManagementFee,PRICING_BASIS,quickOrderLineBreakdown} from '../quick_discount_rules.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {contractQuote} from '../api/contract_quote.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
function source(quantity=1,discount=1){
 const item={name:'合成制造费用柜',product_code:'JP',quantity,quick_discount:discount,formula_discount:1,freight_fee:100,
  material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,specification:'800*600*1800',
  manufacturing_cost_basis:MANUFACTURING_COST_BASIS,attachments:[],pricing_basis:PRICING_BASIS,
  formula:{material_cost:600,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:0},
  quick:{base_price:900,total_cost:900,attachment_fee:0}};
 item.formula=manufacturingFormulaForItem(item);
 const line=quickOrderLineBreakdown({quote:item.quick,attachments:[],discount,cabinetQuantity:quantity,freightFee:100});
 item.quote_display={name:item.name,specification:item.specification,unit:'台',quantity,discount,
  unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:0,material_difference:0,
  quick_base_price:900,quick_attachment_fee:0,quick_total_cost:900,attachments:[],attachment_source:'popup_v1',remark:''};
 return item;
}
test('quote=1000: manufacturing40 + management50; expenses do not compound',()=>{
 const item=source();assert.equal(item.formula.manufacturing_cost,40);
 assert.equal(item.formula.management_fee,50);assert.equal(item.formula.management_fee_base,1000);
 assert.equal(item.formula.total_cost,690);assert.equal(item.formula.management_fee_rate,.05);
 assert.deepEqual(applyManagementFee(item.formula,100),item.formula);
 assert.deepEqual(manufacturingFormulaForItem(item),item.formula);
});
test('discount changes both fees; quantity multiplies the rounded unit expense only once',()=>{
 const item=source(3,.5);
 assert.equal(item.quote_display.unit_price,550);assert.equal(item.formula.manufacturing_cost,22);
 assert.equal(item.formula.management_fee,27.5);assert.equal(item.formula.total_cost,649.5);
 assert.equal(item.quote_display.total,1650);
});
test('old unmarked costs retain their recorded six-percent interpretation',()=>{
 const item=source();delete item.manufacturing_cost_basis;
 item.formula={material_cost:600,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:0};
 assert.equal(applyManagementFee(item.formula,100).management_fee,42);
 assert.deepEqual(manufacturingFormulaForItem(item),item.formula);
});

test('contract formula fallback includes saved manufacture without recalculating history',()=>{
 const item=source(2),snapshot={draft_items:[item]};
 assert.equal(contractQuote(snapshot,'FORMULA').total,1580);
 item.formula.manufacturing_quote_unit_price=99999;
 assert.equal(contractQuote(snapshot,'FORMULA').total,1580,'saved fees are immutable inputs');
 delete item.formula.manufacturing_cost;
 assert.throws(()=>contractQuote(snapshot,'FORMULA'),/成本不完整/);
});
test('API confirmation keeps both expenses and rejects stale client factory/management amounts',async()=>{
 const service=createAttachmentService({runPsql:async()=>{throw Error('no SQL needed for synthetic legacy item');}});
 const item=source(2);
 const hydrated=await service.hydrateDocument({items:[item]});
 assert.equal(hydrated.items[0].formula.manufacturing_cost,40);
 assert.equal(hydrated.items[0].formula.management_fee,50);
 assert.equal(hydrated.items[0].formula.total_cost,690);
 await assert.rejects(service.hydrateDocument({items:[{...item,formula:{...item.formula,manufacturing_cost:0}}]}),/4%/);
 await assert.rejects(service.hydrateDocument({items:[{...item,formula:{...item.formula,management_fee:42}}]}),/5%/);
});
test('real workbook includes manufacture, 5% management, preserved quote and reconciled formula cost',async()=>{
 const outputRoot=path.join(root,'.codex-tmp');await mkdir(outputRoot,{recursive:true});
 const folder=await mkdtemp(path.join(outputRoot,'manufacturing-'));
 try{
  const input=path.join(folder,'input.json'),output=path.join(folder,'output.xlsx');
  await writeFile(input,JSON.stringify({quote_id:'LOCAL-MANUFACTURING',company_name:'合成测试客户',order_nature:'EXTERNAL',
    quotation_detail_layout:'vertical_v1',items:[source(2)]}));
  execFileSync(process.execPath,['export_dual_quote_workbook.mjs',input,output],{cwd:root,windowsHide:true,stdio:'pipe'});
  const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
  const quick=book.getWorksheet('报价'),formula=book.getWorksheet('成本'),details=book.getWorksheet('成本明细');
  assert.equal(quick.getCell('F11').value,1000);assert.equal(quickQuotationAmount(quick.getCell('G11')),2000);
  assert.equal(formula.getCell('F11').value,790);assert.equal(formula.getCell('G11').value,1580);
  let manufacturing=[],management=[];details.eachRow(row=>{
    if(row.getCell(4).value==='制造成本')manufacturing.push(row.values);
    if(row.getCell(4).value==='管理费用')management.push(row.values);
  });
  assert.equal(manufacturing.length,1);assert.equal(manufacturing[0][13],80);
  assert.equal(management.length,1);assert.equal(management[0][13],100);
 }finally{
  assert(path.resolve(folder).startsWith(path.resolve(outputRoot)+path.sep));
  await rm(folder,{recursive:true,force:true});
 }
});
