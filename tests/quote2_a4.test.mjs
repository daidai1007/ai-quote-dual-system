import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import ExcelJS from '@excel.js/exceljs';
import {quotationLayout} from './quotation_layout_reader.mjs';
import {quickOrderLineBreakdown,moneySum,PRICING_BASIS} from '../quick_discount_rules.mjs';
const run=promisify(execFile),root=path.resolve(import.meta.dirname,'..');
const fixture=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/export_formula_cost_detail.json'),'utf8'));
const result=value=>value?.formula?(value.result??0):value;
function payload(count,long=false){
 const p=structuredClone(fixture);p.quote_id='LOCAL-QUOTE2-A4-20261030';p.quote_date='2026-10-30';p.company_name='本机报价2测试客户';p.order_nature='EXTERNAL';
 p.items=Array.from({length:count},(_,i)=>{
  const item=structuredClone(fixture.items[i%fixture.items.length]);item.quantity=i%3+1;item.quick_discount=.83;item.pricing_basis=PRICING_BASIS;
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount:item.quick_discount,cabinetQuantity:item.quantity,freightFee:item.freight_fee||0});
  item.quote_display={name:`打印测试柜${String(i+1).padStart(3,'0')}`,specification:`${item.width_mm}*${item.depth_mm}*${item.height_mm}`,
   quantity:item.quantity,unit:'台',unit_price:line.equivalentUnitTotal,total:line.lineTotal,discount:item.quick_discount,
   attachment_face_price:line.attachmentFee,material_difference:0,quick_base_price:line.basePrice,quick_attachment_fee:line.attachmentFee,
   quick_total_cost:moneySum([line.basePrice,line.attachmentFee]),remark:(long&&i===1?'附件型号数量配套供货，检验资料随货。'.repeat(28):'灯2套、接地线3根、安装附件按确认清单配套。')+`备注结束${String(i+1).padStart(3,'0')}`};return item;
 });return p;
}
async function inDirectory(check){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'quote2-a4-'));
 try{return await check(dir);}finally{assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));assert(path.basename(dir).startsWith('quote2-a4-'));await fs.rm(dir,{recursive:true,force:true});}
}
async function exported(dir,p,vertical){
 const input=path.join(dir,'input.json'),output=path.join(dir,'quote.xlsx');await fs.writeFile(input,JSON.stringify({...p,...(vertical?{quotation_detail_layout:'right_vertical_v1'}:{})}));
 await run(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,windowsHide:true});
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);return {book,output};
}
for(const vertical of [false,true])for(const count of [1,3,12])test(`报价2 contains only A:H, links physical price/quantity rows, and preserves source (${vertical?'vertical':'standard'},${count})`,()=>inDirectory(async dir=>{
 const p=payload(count),{book}=await exported(dir,p,vertical),q=book.getWorksheet('报价'),sheet=book.getWorksheet('报价2'),layout=quotationLayout(q);
 assert.deepEqual(book.worksheets.slice(0,4).map(s=>s.name),['成本','报价','报价2','成本明细']);
 assert.equal(sheet.columnCount,8);assert.equal(sheet.rowCount,count+11);assert.equal(sheet.getCell('D1').value,'编号');assert.equal(result(sheet.getCell('E1').value),p.quote_id);
 assert.equal(result(sheet.getCell('D3').value),'订单性质');assert.equal(result(sheet.getCell('F3').value),'外部');assert(sheet.model.merges.includes('D3:E3'));
 p.items.forEach((item,i)=>{
  const source=layout?.products[i]??11+i;
  for(const column of ['D','F','G'])assert.equal(sheet.getCell(`${column}${11+i}`).value.formula,`'报价'!${column}${source}`);
  assert.equal(result(sheet.getCell(`F${11+i}`).value),item.quote_display.unit_price);assert.equal(result(sheet.getCell(`G${11+i}`).value),item.quote_display.total);
  assert.equal(typeof q.getCell(`F${source}`).value,'number');assert.equal(q.getCell(`G${source}`).value.formula,`ROUND(F${source}*D${source},2)`);
  assert.equal(result(sheet.getCell(`H${11+i}`).value),item.quote_display.remark);
 });
 assert.equal(sheet.getCell(`G${11+count}`).value.formula,`'报价'!G${layout?.subtotal??11+count}`);
 assert.equal(sheet.pageSetup.paperSize,9);assert.equal(sheet.pageSetup.orientation,'portrait');assert.equal(sheet.pageSetup.fitToWidth,1);assert.equal(sheet.pageSetup.fitToHeight,0);
 assert.equal(sheet.pageSetup.printArea,`A1:H${11+count}`);assert.equal(sheet.pageSetup.printTitlesRow,'10:10');
 q.eachRow(row=>row.eachCell(cell=>assert(!cell.value?.formula?.includes('报价2'),'no circular reference from source')));
}));

for(const [name,count,long]of [['short',3,false],['long',3,true],['many',12,false]])test(`native A4 output and source-to-报价2 edits survive save/reopen (${name})`,()=>inDirectory(async dir=>{
 const p=payload(count,long),{book,output}=await exported(dir,p,true),source=book.getWorksheet('报价'),layout=quotationLayout(source),last=11+count;
 const edits={};layout.products.forEach((row,i)=>{if(i<3){edits[`F${row}`]=[123.45,0,10.01][i];edits[`D${row}`]=[3,7,2][i];}});edits.B4='联动测试客户';
 const request=path.join(dir,'native-request.json'),report=path.join(dir,'native-report.json'),saved=path.join(dir,'edited.xlsx'),pdf=path.join(dir,'报价2.pdf');
 await fs.writeFile(request,JSON.stringify({edits,numbers:['D11','F11','G11','G12','G13',`G${last}`],strings:['B4','E1','H12']}));
 const office=process.env.QUOTE_TEST_SOFFICE||'C:/Program Files/LibreOffice/program/soffice.exe';
 await run(path.join(path.dirname(office),'python.exe'),[path.join(root,'tests/helpers/verify_quote2_native.py'),output,saved,pdf,request,report],{windowsHide:true,timeout:60000});
 const native=JSON.parse(await fs.readFile(report,'utf8'));assert.equal(native.automatic,true);assert.equal(native.values.F11,123.45);assert.equal(native.values.D11,3);assert.equal(native.values.G11,370.35);assert.equal(native.values.G12,0);assert.equal(native.values.G13,20.02);assert.equal(native.strings.B4,'联动测试客户');assert.equal(native.strings.E1,p.quote_id);assert.equal(native.strings.H12,p.items[1].quote_display.remark);
 const reopened=new ExcelJS.Workbook();await reopened.xlsx.readFile(saved);const q2=reopened.getWorksheet('报价2');assert.equal(result(q2.getCell('G11').value),370.35);assert.equal(result(q2.getCell(`G${last}`).value),native.values[`G${last}`]);assert(q2.getCell('F11').value.formula.includes('报价'));assert.equal(reopened.getWorksheet('报价').state,'visible');
 const python=process.env.QUOTE_TEST_PYTHON||'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
 const script="import sys,json;from pypdf import PdfReader;p=PdfReader(sys.argv[1]);print(json.dumps({'pages':len(p.pages),'sizes':[[float(x.mediabox.width),float(x.mediabox.height)] for x in p.pages],'text':''.join(x.extract_text() or '' for x in p.pages)},ensure_ascii=False))";
 const inspected=JSON.parse((await run(python,['-c',script,pdf],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}})).stdout);
 assert(inspected.sizes.every(([w,h])=>Math.abs(w-595.28)<1&&Math.abs(h-841.89)<1),'A4 portrait every page');
 if(name==='short')assert.equal(inspected.pages,1,'three normal rows fit one A4 page');else if(name==='many')assert(inspected.pages>=2);
 const text=inspected.text.replace(/\s/g,'');assert(text.includes(p.quote_id));assert(text.includes('联动测试客户'));assert(text.includes('370.35'));assert(text.includes('订单性质'));assert(text.includes('外部'));
 for(let i=0;i<count;i++){assert(text.includes(p.items[i].quote_display.name));assert(text.includes(`备注结束${String(i+1).padStart(3,'0')}`));}
 assert(!text.includes('材料成本'));assert(!text.includes('原价单价'));
 if(process.env.QUOTE2_QA_DIR){const target=path.join(process.env.QUOTE2_QA_DIR,name);await fs.mkdir(target,{recursive:true});for(const f of [output,saved,pdf,report])await fs.copyFile(f,path.join(target,path.basename(f)));await fs.writeFile(path.join(target,'pdf-inspection.json'),JSON.stringify(inspected,null,2));}
}));
test('the deployed export image includes the new public-sheet module',async()=>{
 assert.match(await fs.readFile(path.join(root,'Dockerfile'),'utf8'),/^COPY public_quote_sheet\.mjs \.\//m);
});
