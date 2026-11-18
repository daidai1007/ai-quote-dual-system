import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import ExcelJS from '@excel.js/exceljs';
import {quotationLayout} from './quotation_layout_reader.mjs';
import {quickOrderLineBreakdown,moneySum,moneyProduct,PRICING_BASIS,ATTACHMENT_DISCOUNT_BASIS} from '../quick_discount_rules.mjs';

const run=promisify(execFile), root=path.resolve(import.meta.dirname,'..');
const fixture=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/export_formula_cost_detail.json'),'utf8'));
const amount=cell=>cell.value?.formula?(cell.value.result??0):cell.value;
async function isolated(check){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'quote-detail-links-'));
 try{return await check(dir);}finally{
  assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));
  assert(path.basename(dir).startsWith('quote-detail-links-'));
  await fs.rm(dir,{recursive:true,force:true});
 }
}
function payload(modern=true,ganged=false){
 const payload=structuredClone(fixture);payload.company_name='合成公式联动测试客户';payload.quote_id='LOCAL-DETAIL-LINK';
 const item=structuredClone(fixture.items[0]);item.quantity=3;item.name='合成柜体';item.quick_discount=.97;
 item.freight_fee=5;item.ganged_cabinet_count=ganged?4:1;
 item.attachments=[
  {item_name:'侧板',category_level1:'侧板',quantity:3,unit_price_override:1.005,quick_amount:3.02,formula_amount:1,quick_discount_basis:ATTACHMENT_DISCOUNT_BASIS},
  {item_name:'接地线',quantity:2,unit_price:10,quick_amount:20,formula_amount:1},
  {item_name:'安装板',quantity:1,unit_price:50,quick_amount:50,formula_amount:1},
  {item_name:'扣减安装板',quantity:1,attachment_price_sign:-1,unit_price:20,quick_amount:-20,formula_amount:-1},
  {item_name:'内门',quantity:1,unit_price_override:0,quick_amount:0,formula_amount:0,quick_discount_basis:ATTACHMENT_DISCOUNT_BASIS},
  {item_name:'风机测试件',quantity:1,unit_price:0,quick_amount:0,formula_amount:0},
 ];
 const fee=moneySum(item.attachments.map(row=>row.quick_amount));item.quick={base_price:1000,attachment_fee:fee,total_cost:moneySum([1000,fee])};
 const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount:item.quick_discount,cabinetQuantity:3,gangedCabinetCount:item.ganged_cabinet_count,freightFee:5});
 if(modern){
  item.pricing_basis=PRICING_BASIS;
  item.quote_display={name:item.name,specification:'800*600*1800',quantity:3,unit:'台',discount:.97,
   unit_price:line.equivalentUnitTotal,total:line.lineTotal,attachment_face_price:fee,material_difference:0,
   quick_base_price:1000,quick_attachment_fee:fee,quick_total_cost:item.quick.total_cost,remark:'完整合成备注'};
 }
 payload.items=[item];return payload;
}
async function exported(dir,payload,vertical){
 const input=path.join(dir,'input.json'),output=path.join(dir,'original.xlsx');
 const text=JSON.stringify({...payload,...(vertical?{quotation_detail_layout:'right_vertical_v1'}:{})});
 await fs.writeFile(input,text);
 await run(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,windowsHide:true});
 const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);
 return {book,input,output,text};
}
function positions(book){
 const sheet=book.getWorksheet('报价'),plan=quotationLayout(sheet),row=plan?.products[0]??11;
 const fields=plan?.blocks[0].fields??Array.from({length:sheet.columnCount-9},(_,i)=>({name:sheet.getCell(10,i+10).text,address:sheet.getCell(row,i+10).address}));
 return {sheet,plan,row,subtotal:plan?.subtotal??12,field:name=>{
  const found=fields.find(field=>field.name===name);assert(found,`Missing ${name}`);return found.address;
 }};
}
async function native(dir,output,request,name){
 const edits=path.join(dir,name+'.json'),report=path.join(dir,name+'-report.json'),saved=path.join(dir,name+'.xlsx');
 await fs.writeFile(edits,JSON.stringify(request));
 const office=process.env.QUOTE_TEST_SOFFICE||'C:/Program Files/LibreOffice/program/soffice.exe';
 await run(path.join(path.dirname(office),'python.exe'),[path.join(root,'tests/helpers/recalculate_quote_lo.py'),output,saved,edits,report],{windowsHide:true,timeout:60000});
 return {saved,report:JSON.parse(await fs.readFile(report,'utf8'))};
}
for(const vertical of [false,true])for(const modern of [false,true])for(const ganged of [false,true]){
 test(`actual spreadsheet edits update left prices and 报价2 (${vertical?'vertical':'standard'}, ${modern?'current':'legacy'}, ${ganged?'ganged':'single'})`,()=>isolated(async dir=>{
  const data=payload(modern,ganged),{book,input,output,text}=await exported(dir,data,vertical),p=positions(book);
  const f=`F${p.row}`,g=`G${p.row}`,subtotal=`G${p.subtotal}`;
  assert(p.sheet.getCell(f).value.formula,'left unit price must reference the right inputs');
  assert.equal(p.sheet.getCell(g).value.formula,`ROUND(F${p.row}*D${p.row},2)`);
  const initial=quickOrderLineBreakdown({quote:data.items[0].quick,attachments:data.items[0].attachments,discount:.97,cabinetQuantity:3,freightFee:5}).equivalentUnitTotal;
  const original=quickOrderLineBreakdown({quote:data.items[0].quick,
   attachments:data.items[0].attachments.map(({quick_discount_basis,...attachment})=>attachment),
   discount:1,cabinetQuantity:3,freightFee:5}).equivalentUnitTotal;
  assert.equal(amount(p.sheet.getCell(f)),initial);
  const scale=!modern&&ganged?3:1,freightScale=modern?1:3;
  const check=[f,g,subtotal,p.field('原价单价')];
  const costBefore=book.getWorksheet('成本').getCell(quotationLayout(book.getWorksheet('成本'))?.products[0]??11,6).value;
  const steps=[
   {edits:{},check},
   {edits:{[p.field('侧板')]:75*scale,[p.field('接地线')]:30*scale,[p.field('内门')]:40*scale,[p.field('风机测试件')]:35*scale},check},
   {edits:{[p.field('折扣')]:.8},check},
   {edits:{[p.field('柜体')]:1200*scale,[p.field('运费')]:7.5*freightScale},check},
   {edits:{[p.field('折扣')]:0,[`D${p.row}`]:4},check},
  ];
  const result=await native(dir,output,{steps,check_sheets:{'报价2':['F11','G11','G12']}},'edited');
  assert.equal(result.report.automatic,true);
  const expected=[initial,1180.65,986,1148.5,72.5];
  result.report.steps.forEach((step,i)=>{
   assert.equal(step.values[f],expected[i],`step ${i} unit price`);
   assert.equal(step.values[g],moneyProduct(expected[i],i===4?4:3));
   assert.equal(step.values[subtotal],step.values[g]);
   assert.equal(step.sheets['报价2'].F11,expected[i]);
   assert.equal(step.sheets['报价2'].G11,step.values[g]);
   assert.equal(step.sheets['报价2'].G12,step.values[subtotal]);
  });
  assert.equal(result.report.steps[0].values[p.field('原价单价')],original,'original-price formula agrees with its saved cache');
  const opened=new ExcelJS.Workbook();await opened.xlsx.readFile(result.saved);
  const reopened=positions(opened);assert.equal(amount(reopened.sheet.getCell(f)),72.5);
  assert.equal(amount(reopened.sheet.getCell(g)),290);assert(reopened.sheet.getCell(f).value.formula);
  const cost=opened.getWorksheet('成本');assert.equal(cost.getCell(quotationLayout(cost)?.products[0]??11,6).value,costBefore);
  const reopenedNative=await native(dir,result.saved,{edits:{},check:[f,g,subtotal]},'reopened');
  assert.equal(reopenedNative.report.values[f],72.5);assert.equal(reopenedNative.report.values[g],290);
  assert.equal(await fs.readFile(input,'utf8'),text,'export must not write back to the quote snapshot');
 }));
}

function refreshDisplay(item,materialDifference=0){
 const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount:item.quick_discount,
  cabinetQuantity:item.quantity,freightFee:item.freight_fee??0,materialDifference});
 Object.assign(item.quote_display,{quantity:item.quantity,discount:item.quick_discount,unit_price:line.equivalentUnitTotal,
  total:line.lineTotal,attachment_face_price:line.attachmentFee,material_difference:materialDifference,
  quick_base_price:line.basePrice,quick_attachment_fee:line.attachmentFee,quick_total_cost:item.quick.total_cost});
}
test('editing one product does not alter another; formerly blank category inputs participate',()=>isolated(async dir=>{
 const data=payload(),other=structuredClone(data.items[0]);
 other.name='第二组合成柜体';other.attachments=[];other.quick={base_price:600,total_cost:600,attachment_fee:0};
 other.quantity=2;other.quick_discount=.5;other.freight_fee=0;refreshDisplay(other);
 data.items.push(other);
 const {book,output}=await exported(dir,data,true),p=positions(book),second=p.plan.blocks[1];
 const find=name=>second.fields.find(f=>f.name===name).address,row=p.plan.products[1];
 assert.equal(p.sheet.getCell(find('内门')).value,null);
 const check=[`F${p.row}`,`G${p.row}`,`F${row}`,`G${row}`,`G${p.subtotal}`];
 const result=await native(dir,output,{steps:[
  {edits:{[p.field('接地线')]:30},check},
  {edits:{[find('内门')]:40,[find('风机测试件')]:35},check},
 ]},'two-products');
 assert.equal(result.report.steps[0].values[`F${p.row}`],1037.01);
 assert.equal(result.report.steps[0].values[`F${row}`],300);
 assert.equal(result.report.steps[1].values[`F${p.row}`],1037.01);
 assert.equal(result.report.steps[1].values[`F${row}`],355);
 assert.equal(result.report.steps[1].values[`G${p.subtotal}`],3821.03);
}));

test('a shared accessory name retains each selected row discount rule and proportional allocation',()=>isolated(async dir=>{
 const data=payload(),item=data.items[0];
 item.attachments=[
  {item_name:'合并附件',category_level1:'侧板',quantity:1,unit_price_override:100,quick_amount:100,formula_amount:1,quick_discount_basis:ATTACHMENT_DISCOUNT_BASIS},
  {item_name:'合并附件',category_level1:'风机',quantity:1,unit_price_override:50,quick_amount:50,formula_amount:1,quick_discount_basis:ATTACHMENT_DISCOUNT_BASIS},
 ];
 item.quick={base_price:1000,total_cost:1150,attachment_fee:150};refreshDisplay(item);
 const {book,output}=await exported(dir,data,true),p=positions(book),f=`F${p.row}`,check=[f];
 const result=await native(dir,output,{steps:[
  {edits:{},check},
  {edits:{[p.field('合并附件')]:300,[p.field('折扣')]:.8},check},
  {edits:{[p.field('折扣')]:.5},check},
 ]},'mixed-category');
 assert.deepEqual(result.report.steps.map(step=>step.values[f]),[1122,1065,705]);
 const zeroFolder=path.join(dir,'zero-first');await fs.mkdir(zeroFolder);
 item.attachments=[
  {item_name:'同名附件',category_level1:'风机',quantity:0,quick_amount:0,formula_amount:0},
  {item_name:'同名附件',category_level1:'安装板',quantity:1,unit_price:100,quick_amount:100,formula_amount:1},
 ];
 item.quick={base_price:1000,total_cost:1100,attachment_fee:100};refreshDisplay(item);
 const zeroBook=await exported(zeroFolder,data,true),z=positions(zeroBook.book);
 const edited=await native(zeroFolder,zeroBook.output,{edits:{[z.field('同名附件')]:200,[z.field('折扣')]:.8},check:[`F${z.row}`]},'zero-first');
 assert.equal(edited.report.values[`F${z.row}`],965,'a zero-count record cannot change the active category');
}));

test('popup snapshot and material difference feed the price; legacy left-price discrepancies are overwritten',()=>isolated(async dir=>{
 for(const legacy of [false,true]){
  const data=payload(!legacy),item=data.items[0];
  if(legacy){
   const original=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,discount:.97,cabinetQuantity:3,freightFee:5});
   item.quote_display={quantity:3,discount:.97,unit_price:moneySum([original.equivalentUnitTotal,12.34]),
    total:moneyProduct(moneySum([original.equivalentUnitTotal,12.34]),3)};
  }else{
   item.material_code='SUS316';item.formula.corrected_material_weight_kg=2;
   item.formula.material_details=[];item.formula.cabinet_material_part_details=[];
   refreshDisplay(item,50);item.quote_display.attachments=structuredClone(item.attachments);
   item.quote_display.attachment_source='popup_v1';
  }
  const folder=path.join(dir,legacy?'legacy':'popup');await fs.mkdir(folder);
  const {book,output}=await exported(folder,data,true),p=positions(book),f=`F${p.row}`,check=[f];
  const result=await native(folder,output,{steps:[{edits:{},check},{edits:legacy?
   {[p.field('接地线')]:30}:{[p.field('材料差价')]:100},check}]},'frozen');
  assert.deepEqual(result.report.steps.map(step=>step.values[f]),legacy?[1027.01,1037.01]:[1077.01,1127.01]);
 }
}));

test('right details completely overwrite higher and lower saved left prices on export, edit and reopen',()=>isolated(async dir=>{
 for(const openingPrice of [1200,950]){
  const folder=path.join(dir,String(openingPrice));await fs.mkdir(folder);
  const data=payload(false),item=data.items[0];
  item.freight_fee=0;item.quick_discount=.8;
  item.attachments=[
   {item_name:'侧板',category_level1:'侧板',quantity:1,unit_price:200,quick_amount:200,formula_amount:1},
   {item_name:'接地线',quantity:1,unit_price:100,quick_amount:100,formula_amount:1},
  ];
  item.quick={base_price:1000,attachment_fee:300,total_cost:1300};
  item.quote_display={quantity:3,unit_price:openingPrice,total:openingPrice*3,discount:.8};
  const {book,output}=await exported(folder,data,true),p=positions(book),f=`F${p.row}`,g=`G${p.row}`;
  const check=[f,g,`G${p.subtotal}`],checks={'报价2':['F11','G11','G12']};
  assert.equal(amount(p.sheet.getCell(f)),1060);
  assert.equal(amount(p.sheet.getCell(g)),3180);
  assert.equal(amount(book.getWorksheet('报价2').getCell('F11')),1060);
  const request={steps:[
   {edits:{},check},
   {edits:{[p.field('侧板')]:300},check},
   {edits:{[p.field('接地线')]:150},check},
   {edits:{[p.field('折扣')]:.9},check},
   {edits:{[p.field('侧板')]:200},check},
   {edits:{[p.field('接地线')]:100,[p.field('折扣')]:.8},check},
  ],check_sheets:checks};
  const edited=await native(folder,output,request,'right-overwrite');
  const expectedPrices=[1060,1140,1190,1320,1230,1060];
  edited.report.steps.forEach((step,index)=>{
   const expected=expectedPrices[index];
   assert.equal(step.values[f],expected);
   assert.equal(step.values[g],moneyProduct(expected,3));
   assert.equal(step.values[`G${p.subtotal}`],step.values[g]);
   assert.equal(step.sheets['报价2'].F11,expected);
   assert.equal(step.sheets['报价2'].G12,step.values[g]);
  });
  const reopened=await native(folder,edited.saved,{edits:{[p.field('侧板')]:300},check,check_sheets:checks},'right-overwrite-reopened');
  assert.equal(reopened.report.values[f],1140);
  assert.equal(reopened.report.steps[0].sheets['报价2'].F11,1140);
 }
}));

test('A4 print contains the amounts recalculated from edited right-side prices and discount',()=>isolated(async dir=>{
 const data=payload(),{book,output}=await exported(dir,data,true),p=positions(book);
 const request=path.join(dir,'print-request.json'),report=path.join(dir,'print-report.json');
 const saved=path.join(dir,'print-edited.xlsx'),pdf=path.join(dir,'print-edited.pdf');
 await fs.writeFile(request,JSON.stringify({edits:{[p.field('接地线')]:30,[p.field('折扣')]:.8},
  numbers:['F11','G11','G12'],strings:['H11']}));
 const office=process.env.QUOTE_TEST_SOFFICE||'C:/Program Files/LibreOffice/program/soffice.exe';
 await run(path.join(path.dirname(office),'python.exe'),[path.join(root,'tests/helpers/verify_quote2_native.py'),
  output,saved,pdf,request,report],{windowsHide:true,timeout:60000});
 const observed=JSON.parse(await fs.readFile(report,'utf8'));
 assert.equal(observed.values.F11,861.4);assert.equal(observed.values.G11,2584.2);assert.equal(observed.values.G12,2584.2);
 assert.equal(observed.strings.H11,'完整合成备注');
 const python=process.env.QUOTE_TEST_PYTHON||'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
 const script="import sys,json;from pypdf import PdfReader;p=PdfReader(sys.argv[1]);print(json.dumps({'pages':len(p.pages),'sizes':[[float(x.mediabox.width),float(x.mediabox.height)] for x in p.pages],'text':''.join(x.extract_text() or '' for x in p.pages)},ensure_ascii=False))";
 const inspected=JSON.parse((await run(python,['-c',script,pdf],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}})).stdout);
 assert.equal(inspected.pages,1);assert(inspected.sizes.every(([w,h])=>Math.abs(w-595.28)<1&&Math.abs(h-841.89)<1));
 const text=inspected.text.replace(/\s/g,'');assert(text.includes('861.40'));assert(text.includes('2,584.20'));assert(text.includes('完整合成备注'));
 if(process.env.QUOTE_DETAIL_QA_DIR){
  await fs.mkdir(process.env.QUOTE_DETAIL_QA_DIR,{recursive:true});
  for(const file of [output,saved,pdf,request,report])await fs.copyFile(file,path.join(process.env.QUOTE_DETAIL_QA_DIR,path.basename(file)));
 }
}));
