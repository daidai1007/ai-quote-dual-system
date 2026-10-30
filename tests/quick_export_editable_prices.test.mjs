import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import ExcelJS from '@excel.js/exceljs';
import {unzipSync,strFromU8} from 'fflate';
import {quotationLayout} from './quotation_layout_reader.mjs';
import {quickOrderLineBreakdown,moneySum,PRICING_BASIS} from '../quick_discount_rules.mjs';
const run=promisify(execFile),root=path.resolve(import.meta.dirname,'..');
const fixture=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/export_formula_cost_detail.json'),'utf8'));
// ExcelJS omits an explicit zero result while reading some Office formula
// caches; a zero is still a numeric result, not the formula object itself.
const numeric=value=>value?.formula?(value.result??0):value;
async function isolated(check){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'quick-edit-price-'));
 try{return await check(dir);}finally{
  assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));assert(path.basename(dir).startsWith('quick-edit-price-'));
  await fs.rm(dir,{recursive:true,force:true});
 }
}
function currentPayload(count){
 const payload=structuredClone(fixture);payload.company_name='本机合成测试客户';payload.quote_id='LOCAL-EDIT-PRICE';
 payload.items=Array.from({length:count},(_,i)=>{
  const item=structuredClone(fixture.items[i%fixture.items.length]);item.quantity=i%3+1;item.name='合成柜体'+(i+1);item.source_pdf_name='合成柜体'+(i+1)+'.pdf';
  item.quick_discount=i%2?0.83:1;item.pricing_basis=PRICING_BASIS;
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount:item.quick_discount,cabinetQuantity:item.quantity,freightFee:item.freight_fee||0});
  item.quote_display={name:item.name,specification:`${item.width_mm}*${item.depth_mm}*${item.height_mm}`,quantity:item.quantity,unit:'台',discount:item.quick_discount,
   unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:line.attachmentFee,material_difference:0,
   quick_base_price:line.basePrice,quick_attachment_fee:line.attachmentFee,quick_total_cost:moneySum([line.basePrice,line.attachmentFee]),remark:'测试备注'};
  return item;
 });return payload;
}
async function exported(dir,payload,vertical){
 const input=path.join(dir,'input.json'),output=path.join(dir,'quote.xlsx');
 await fs.writeFile(input,JSON.stringify({...payload,...(vertical?{quotation_detail_layout:'right_vertical_v1'}:{})}));
 await run(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,windowsHide:true});
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);return {book,input,output};
}
for(const vertical of [false,true])for(const count of [1,3,9]){
 test(`saved quick export keeps original totals and formula links (${vertical?'vertical':'standard'}, ${count} products)`,()=>isolated(async dir=>{
  const payload=currentPayload(count),original=JSON.stringify(payload),{book,input,output}=await exported(dir,payload,vertical),sheet=book.getWorksheet('报价'),layout=quotationLayout(sheet);
  const rows=layout?.products??payload.items.map((_,i)=>11+i),subtotal=layout?.subtotal??11+count;
  rows.forEach((row,i)=>{
   assert.equal(numeric(sheet.getCell(row,6).value),payload.items[i].quote_display.unit_price);
   assert.equal(typeof sheet.getCell(row,6).value,'number');
   assert.equal(sheet.getCell(row,7).value.formula,`ROUND(F${row}*D${row},2)`);
   assert.equal(sheet.getCell(row,7).value.result,payload.items[i].quote_display.total);
  });
  assert.equal(sheet.getCell(subtotal,7).value.formula,`SUM(G${rows[0]}:G${rows.at(-1)})`);
  assert.equal(sheet.getCell(subtotal,7).value.result,moneySum(payload.items.map(i=>i.quote_display.total)));
  assert.match(strFromU8(unzipSync(await fs.readFile(output))['xl/workbook.xml']),/fullCalcOnLoad="1"/);
  assert.equal(JSON.stringify(payload),original);
  assert.equal((await fs.readFile(input,'utf8')),JSON.stringify({...payload,...(vertical?{quotation_detail_layout:'right_vertical_v1'}:{})}));
 }));
}
test('historical ganged quotation still exports its frozen amounts',()=>isolated(async dir=>{
 const payload=structuredClone(fixture);payload.items[0].ganged_cabinet_count=2;
 const {book}=await exported(dir,payload,true),sheet=book.getWorksheet('报价'),layout=quotationLayout(sheet);
 for(const row of layout.products)assert.equal(sheet.getCell(row,7).value.formula,`ROUND(F${row}*D${row},2)`);
 assert(Number.isFinite(sheet.getCell(layout.subtotal,7).value.result));
}));
test('LibreOffice recalculates edited prices, quantities and subtotal, including zero, then persists results',()=>isolated(async dir=>{
 const payload=currentPayload(3),{book,input,output}=await exported(dir,payload,true),sheet=book.getWorksheet('报价'),layout=quotationLayout(sheet),cost=book.getWorksheet('成本');
 const costLayout=quotationLayout(cost),costBefore=costLayout.products.map(row=>[numeric(cost.getCell(row,6).value),numeric(cost.getCell(row,7).value)]);
 const [a,b,c]=layout.products;
 const edits=path.join(dir,'edits.json'),report=path.join(dir,'native-report.json');
 await fs.writeFile(edits,JSON.stringify({edits:{[`F${a}`]:123.45,[`D${a}`]:3,[`F${b}`]:0,[`D${b}`]:7,[`F${c}`]:10.01,[`D${c}`]:2},check:[`G${a}`,`G${b}`,`G${c}`,`G${layout.subtotal}`]}));
 const saved=path.join(dir,'edited.xlsx');
 const office=process.env.QUOTE_TEST_SOFFICE||'C:/Program Files/LibreOffice/program/soffice.exe';
 await run(path.join(path.dirname(office),'python.exe'),[path.join(root,'tests/helpers/recalculate_quote_lo.py'),output,saved,edits,report],{windowsHide:true,timeout:60000});
 const native=JSON.parse(await fs.readFile(report,'utf8'));assert.equal(native.automatic,true);assert.equal(native.values[`G${a}`],370.35);assert.equal(native.values[`G${b}`],0);assert.equal(native.values[`G${c}`],20.02);assert.equal(native.values[`G${layout.subtotal}`],390.37);
 const opened=new ExcelJS.Workbook();await opened.xlsx.readFile(saved);
 const out=opened.getWorksheet('报价');
 assert.equal(numeric(out.getCell(a,7).value),370.35);assert.equal(numeric(out.getCell(b,7).value),0);
 assert.equal(numeric(out.getCell(c,7).value),20.02);assert.equal(numeric(out.getCell(layout.subtotal,7).value),390.37);
 assert(out.getCell(a,7).value.formula);assert(out.getCell(layout.subtotal,7).value.formula);
 const costAfter=opened.getWorksheet('成本');assert.deepEqual(costLayout.products.map(row=>[numeric(costAfter.getCell(row,6).value),numeric(costAfter.getCell(row,7).value)]),costBefore);
 const original=JSON.parse(await fs.readFile(input,'utf8'));assert.equal(original.items[0].quote_display.unit_price,payload.items[0].quote_display.unit_price);
}));
