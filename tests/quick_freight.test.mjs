import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import ExcelJS from '@excel.js/exceljs';
import {quickFreightFee,QUICK_FREIGHT_BASIS,MANUFACTURING_COST_BASIS,manufacturingFormulaForItem,
 PRICING_BASIS,validateQuoteDisplay} from '../quick_discount_rules.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';
import {contractQuote} from '../api/contract_quote.mjs';
import {deliveryDocument} from '../api/quote_delivery_document.mjs';
import {withTaxCostForItem,TAX_COST_BASIS} from '../tax_cost.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
function source(){
 const item={name:'合成快速运费测试',product_code:'JP',quantity:2,quick_discount:1,formula_discount:1,freight_fee:100,
  quick_freight_fee:200,quick_freight_mode:'MANUAL',quick_freight_basis:QUICK_FREIGHT_BASIS,
  manufacturing_cost_basis:MANUFACTURING_COST_BASIS,attachments:[],pricing_basis:PRICING_BASIS,
  material_code:'SECC',width_mm:800,height_mm:1800,depth_mm:600,specification:'800*600*1800',
  formula:{material_cost:600,auxiliary_cost:0,labor_cost:0,spray_cost:0,attachment_fee:0},
  quick:{base_price:900,total_cost:900,attachment_fee:0}};
 item.formula=manufacturingFormulaForItem(item);
 item.quote_display={name:item.name,specification:item.specification,unit:'台',quantity:2,discount:1,unit_price:1100,total:2200,
  attachment_face_price:0,material_difference:0,quick_base_price:900,quick_attachment_fee:0,quick_total_cost:900,
  attachment_source:'popup_v1',attachments:[],remark:''};
 return item;
}
test('default follows cost, manual zero is independent, invalid quick freight is rejected',()=>{
 const item={freight_fee:100};assert.equal(quickFreightFee(item),100);
 Object.assign(item,{quick_freight_basis:QUICK_FREIGHT_BASIS,quick_freight_mode:'FOLLOW_COST'});
 item.freight_fee=120;assert.equal(quickFreightFee(item),120);
 Object.assign(item,{quick_freight_mode:'MANUAL',quick_freight_fee:0});
 assert.equal(quickFreightFee(item),0);assert.equal(item.freight_fee,120);
 for(const bad of [-1,null,'',true,'NaN']){item.quick_freight_fee=bad;assert.throws(()=>quickFreightFee(item),/运费/);}
});
test('canonical quoted price includes quick freight once; cost freight stays unchanged',()=>{
 const item=source();validateQuoteDisplay(item);
 assert.equal(item.formula.manufacturing_cost,44);assert.equal(item.formula.management_fee,55);
 assert.equal(item.formula.total_cost+item.freight_fee,799);
 assert.equal(contractQuote({draft_items:[item]},'FORMULA').total,1598);
 assert.equal(contractQuote({draft_items:[item]},'QUICK').total,2200);
 item.freight_fee=120;validateQuoteDisplay(item);
 item.quote_display.unit_price=1200;assert.throws(()=>validateQuoteDisplay(item),/不一致/);
});
test('API validation preserves override, and recipient snapshot distinguishes both freights',async()=>{
 const item=source();const service=createAttachmentService({runPsql:async()=>{throw Error('synthetic legacy row needs no SQL');}});
 const hydrated=await service.hydrateDocument({items:[item]});
 assert.equal(hydrated.items[0].quick_freight_fee,200);assert.equal(hydrated.items[0].freight_fee,100);
 const doc=deliveryDocument({draft_items:[item],document:{order_nature:'EXTERNAL'}},'LOCAL-QUICK-FREIGHT',1);
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('报价运费')],200);
 assert.equal(doc.cost_snapshot.items[0].columns[doc.cost_snapshot.headers.indexOf('运费')],100);
 assert.equal(doc.items[0].total,2200);
});
test('actual Excel quick total uses200, formula total uses100, both reconcile',async()=>{
 const outputRoot=path.join(root,'.codex-tmp');await mkdir(outputRoot,{recursive:true});
 const folder=await mkdtemp(path.join(outputRoot,'quick-freight-'));
 try{
  const input=path.join(folder,'input.json'),output=path.join(folder,'output.xlsx');
  await writeFile(input,JSON.stringify({quote_id:'LOCAL-QUICK-FREIGHT',company_name:'合成测试客户',order_nature:'EXTERNAL',
   quotation_detail_layout:'vertical_v1',items:[source()]}));
  execFileSync(process.execPath,['export_dual_quote_workbook.mjs',input,output],{cwd:root,windowsHide:true,stdio:'pipe'});
  const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
  const quick=book.getWorksheet('报价'),formula=book.getWorksheet('成本');
  assert.equal(quick.getCell('F11').value,1100);assert.equal(quick.getCell('G11').value,2200);
  assert.equal(formula.getCell('F11').value,799);assert.equal(formula.getCell('G11').value,1598);
 }finally{
  assert(path.resolve(folder).startsWith(path.resolve(outputRoot)+path.sep));await rm(folder,{recursive:true,force:true});
 }
});

test('actual current and legacy Excel layouts route quick and cost freight to their own sheets, including manual zero',async()=>{
 const outputRoot=path.join(root,'test-output');await mkdir(outputRoot,{recursive:true});
 const folder=await mkdtemp(path.join(outputRoot,'freight-routing-'));
 try{
  const first=source();first.tax_cost_basis=TAX_COST_BASIS;first.formula=withTaxCostForItem(first);
  const second=source();second.name='合成零快速运费';second.quantity=3;second.quick_freight_fee=0;
  Object.assign(second.quote_display,{name:second.name,quantity:3,unit_price:900,total:2700});
  second.formula=manufacturingFormulaForItem(second);second.tax_cost_basis=TAX_COST_BASIS;second.formula=withTaxCostForItem(second);
  for(const layout of ['horizontal_legacy','right_vertical_v1']){
   const input=path.join(folder,layout+'.json'),output=path.join(folder,layout+'.xlsx');
   await writeFile(input,JSON.stringify({quote_id:'LOCAL-FREIGHT-ROUTING',company_name:'合成测试客户',order_nature:'EXTERNAL',quotation_detail_layout:layout,items:[first,second]}));
   execFileSync(process.execPath,['export_dual_quote_workbook.mjs',input,output],{cwd:root,windowsHide:true,stdio:'pipe'});
   const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
   for(const [name,units,totals,freights] of [
    ['报价',[1100,900],[2200,2700],[200,0]],
    ['成本',[859,811],[1718,2433],[100,100]],
   ]){
    const sheet=book.getWorksheet(name),publicRows=[];
    sheet.eachRow((row,index)=>{const cell=row.getCell(1);if(!cell.isMerged||cell.master.address===cell.address){if([1,2].includes(cell.value)&&row.getCell(5).text==='台')publicRows.push(index);}});
    assert.equal(publicRows.length,2);
    for(let index=0;index<2;index++){
     assert.equal(sheet.getRow(publicRows[index]).getCell(6).value,units[index],name+' unit');
     assert.equal(sheet.getRow(publicRows[index]).getCell(7).value,totals[index],name+' total');
    }
    if(layout==='right_vertical_v1'){
     let header;sheet.getRow(10).eachCell(cell=>{if(cell.text==='项目')header=cell;});assert.ok(header);
     let freightRow;sheet.eachRow((row,index)=>{const cell=row.getCell(header.col);if(cell.text==='运费'&&(!cell.isMerged||cell.master.address===cell.address))freightRow=index;});assert.ok(freightRow);
     for(let index=0;index<2;index++)assert.equal(Number(sheet.getCell(freightRow,header.col+1+index).value||0),freights[index],name+' freight detail');
    }else{
     let column;sheet.getRow(10).eachCell(cell=>{if(cell.text==='运费')column=cell.col;});assert.ok(column);
     for(let index=0;index<2;index++)assert.equal(Number(sheet.getCell(publicRows[index],column).value||0),freights[index],name+' freight detail');
    }
   }
  }
  assert.equal(first.freight_fee,100);assert.equal(second.freight_fee,100);assert.equal(second.quick_freight_fee,0);
 }finally{
  assert(path.resolve(folder).startsWith(path.resolve(outputRoot)+path.sep));await rm(folder,{recursive:true,force:true});
 }
});
