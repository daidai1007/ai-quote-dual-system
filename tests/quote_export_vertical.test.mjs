import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import {unzipSync} from 'fflate';
import {DOMParser} from '@xmldom/xmldom';
import {quotationLayout} from './quotation_layout_reader.mjs';
import {money,PRICING_BASIS,quickOrderLineBreakdown,moneySum,effectiveAttachmentLineAmount} from '../quick_discount_rules.mjs';
const run=promisify(execFile),root=path.resolve(import.meta.dirname,'..');
const fixture=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/export_formula_cost_detail.json'),'utf8'));
const baseline=JSON.parse(await fs.readFile(path.join(root,'tests/fixtures/quote_left_layout_baseline.json'),'utf8'));
const normalize=value=>JSON.parse(JSON.stringify(value));
async function exported(payload,check){
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'quote-vertical-'));
 try{
  const input=path.join(dir,'input.json'),output=path.join(dir,'quote.xlsx');
  await fs.writeFile(input,JSON.stringify({...payload,quotation_detail_layout:'right_vertical_v1'}));
  await run(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),input,output],{cwd:root,windowsHide:true});
  const bytes=await fs.readFile(output);
  const book=new ExcelJS.Workbook();await book.xlsx.readFile(output);await check(book,unzipSync(bytes));
 }finally{
  assert.equal(path.dirname(path.resolve(dir)),path.resolve(os.tmpdir()));
  assert(path.basename(dir).startsWith('quote-vertical-'));
  await fs.rm(dir,{recursive:true,force:true});
 }
}
function height(sheet,first,last){let n=0;for(let r=first;r<=last;r++)n+=sheet.getRow(r).height??sheet.properties.defaultRowHeight??15;return n;}
function endOfMerge(sheet,row,column){const cell=sheet.getCell(row,column);const merge=sheet.model.merges.find(m=>m.startsWith(cell.address+':'));return merge?Number(/\d+$/.exec(merge)[0]):row;}
function evaluate(sheet,address,visiting=new Set()){
 assert(!visiting.has(address),'no circular reference');
 const value=sheet.getCell(address).value;
 if(!value?.formula)return Number(value||0);
 visiting.add(address);
 const expr=value.formula.replace(/\b[A-Z]+\d+\b/g,r=>String(evaluate(sheet,r,visiting)));
 visiting.delete(address);assert.match(expr,/^[\d\s.eE+*/(),\-ROUND]+$/);
 return Function('ROUND',`"use strict";return (${expr});`)((n,p)=>{assert.equal(p,2);return money(n);});
}

test('serialized merged cells retain both vertical edges and the last-row bottom border for every left cell',async()=>{
 await exported(fixture,(book,entries)=>{
  const parse=bytes=>new DOMParser().parseFromString(Buffer.from(bytes).toString('utf8'),'application/xml');
  const styles=parse(entries['xl/styles.xml']);
  const children=(node,name)=>Array.from(node.childNodes).filter(c=>c.nodeType===1&&c.nodeName===name);
  const xfs=children(styles.getElementsByTagName('cellXfs')[0],'xf');
  const borders=children(styles.getElementsByTagName('borders')[0],'border');
  for(const [name,old] of Object.entries(baseline)){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   const xml=parse(entries[`xl/worksheets/sheet${sheet.id}.xml`]);
   const cells=new Map(Array.from(xml.getElementsByTagName('c')).map(c=>[c.getAttribute('r'),c]));
   for(const source of old.rows.filter(row=>row.row>=11)){
    const first=plan.products[source.row-11]??plan.subtotal,last=endOfMerge(sheet,first,2);
    for(let column=1;column<=8;column++){
     const expected=old.styles[source.cells[column-1].style].border||{};
     for(let row=first;row<=last;row++){
      const address=sheet.getCell(row,column).address,cell=cells.get(address);
      assert(cell,`${name}/${address} must be serialized`);
      const border=borders[Number(xfs[Number(cell.getAttribute('s')||0)].getAttribute('borderId')||0)];
      const edges=['left','right',...(row===first?['top']:[]),...(row===last?['bottom']:[])];
      for(const edge of edges){
       const actual=children(border,edge)[0];
       assert.equal(actual?.getAttribute('style')||undefined,expected[edge]?.style,`${name}/${address} ${edge} physical border`);
       if(expected[edge]?.color?.argb)assert.equal(children(actual,'color')[0]?.getAttribute('rgb'),expected[edge].color.argb);
      }
     }
    }
   }
   for(const first of [10,...plan.blocks[0].fields.map(field=>field.row)]){
    const last=endOfMerge(sheet,first,plan.first);
    for(let column=plan.first;column<=plan.first+plan.blocks.length;column++)for(let row=first;row<=last;row++){
     const address=sheet.getCell(row,column).address,cell=cells.get(address);assert(cell,address);
     const border=borders[Number(xfs[Number(cell.getAttribute('s')||0)].getAttribute('borderId')||0)];
     for(const edge of ['left','right',...(row===first?['top']:[]),...(row===last?['bottom']:[])]){
      assert.equal(children(border,edge)[0]?.getAttribute('style'),'thin',`${name}/${address} right table ${edge}`);
     }
    }
   }
  }
 });
});

test('current unit-set matrix totals reference each numeric product quantity, never a product heading',async()=>{
 const payload=structuredClone(fixture);payload.items[1].quantity=3;
 payload.items.forEach((item,index)=>{
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:item.attachments,
   discount:item.quick_discount??1,cabinetQuantity:item.quantity,gangedCabinetCount:1,freightFee:item.freight_fee||0});
  item.pricing_basis=PRICING_BASIS;
  item.quote_display={name:`合成测试柜${index+1}`,specification:`${item.width_mm}*${item.depth_mm}*${item.height_mm}`,
   quantity:item.quantity,unit:'台',unit_price:line.equivalentUnitTotal,total:line.lineTotal,
   discount:item.quick_discount??1,attachments:item.attachments,
   attachment_face_price:moneySum(item.attachments.map(a=>effectiveAttachmentLineAmount(a,1,1))),material_difference:0,
   quick_base_price:line.basePrice,quick_attachment_fee:item.quick.attachment_fee,quick_total_cost:item.quick.total_cost,
   remark:item.final_remark||item.notes||''};
 });
 await exported(payload,book=>{
  const sheet=book.getWorksheet('快速报价单'),plan=quotationLayout(sheet);
  assert.equal(plan.layout,'matrix');
  plan.blocks.forEach((block,index)=>{
   const unit=block.fields.find(field=>field.name==='原价单价');
   const total=block.fields.find(field=>field.name==='原价总价');assert(unit&&total);
   const formula=sheet.getCell(total.address).value.formula;
   assert.equal(formula,`ROUND(${unit.address}*D${plan.products[index]},2)`);
   assert.equal(evaluate(sheet,total.address),money(payload.items[index].quick.total_cost*payload.items[index].quantity));
   assert(Number.isFinite(evaluate(sheet,total.address)));
  });
 });
});

test('saved left quotation retains every value/style, column width and original visual row height',async()=>{
 await exported(fixture,book=>{
  for(const [name,old] of Object.entries(baseline)){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   assert.deepEqual(Array.from({length:8},(_,i)=>sheet.getColumn(i+1).width),old.widths);
   assert.deepEqual(sheet.views,old.views);
   for(const merge of old.headerMerges)assert(sheet.model.merges.includes(merge));
   for(const row of old.rows){
    const actualRow=row.row<11?row.row:plan.products[row.row-11]??plan.subtotal;
    const last=row.row<11?actualRow:endOfMerge(sheet,actualRow,2);
    assert(Math.abs(height(sheet,actualRow,last)-row.height)<.00001);
    let pixels=0;for(let r=actualRow;r<=last;r++)pixels+=Math.round((sheet.getRow(r).height??15)*4/3);
    assert.equal(pixels,Math.round(row.height*4/3),'original visible height after normal-zoom pixel rounding');
    row.cells.forEach((cell,i)=>{
     const actual=sheet.getCell(actualRow,i+1);
     assert.deepEqual(normalize(actual.value),cell.value,`${name} value ${row.row}/${i+1}`);
     assert.deepEqual(normalize(actual.style),old.styles[cell.style],`${name} style ${row.row}/${i+1}`);
    });
   }
   assert.equal(plan.blocks[0].row,10);
   assert.equal(sheet.columnCount,plan.first+fixture.items.length,'one value column per product, no obsolete wide columns');
  }
 });
});

test('ordinary detail rows have the same visible height as the item header',async()=>{
 await exported(fixture,book=>{
  for(const name of ['公式法报价单','快速报价单']){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   const pixels=(first,last)=>{
    let total=0;for(let row=first;row<=last;row++)total+=Math.round((sheet.getRow(row).height??15)*4/3);
    return total;
   };
   const expected=pixels(10,endOfMerge(sheet,10,plan.first));
   assert.equal(expected,44,'retain the established 33pt header display height');
   for(const block of plan.blocks)for(const field of block.fields){
    assert.equal(pixels(field.row,endOfMerge(sheet,field.row,plan.first)),expected,
      `${name}/${field.name} should be as tall as the item header`);
   }
  }
 });
});

test('each product has its own ordered, typed vertical details with live relocated formulas',async()=>{
 await exported(fixture,book=>{
  for(const name of ['公式法报价单','快速报价单']){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   assert.equal(plan.blocks.length,fixture.items.length);
   assert.equal(plan.layout,'matrix');
   const headers=plan.blocks[0].fields.map(f=>f.name);
   assert.deepEqual(headers.slice(-2),['运费','折扣']);
   plan.blocks.forEach((block,i)=>{
    assert.equal(block.row,10,'product headings share the original header row');
    assert.equal(block.column,plan.first+1+i,'products are displayed side by side');
    assert.match(block.name,new RegExp(`^0${i+1} · `));
    assert.deepEqual(block.fields.map(f=>f.name),headers);
    assert.deepEqual(block.fields.map(f=>f.row),plan.blocks[0].fields.map(f=>f.row),'all products share the same item rows');
    for(const f of block.fields){
     const value=sheet.getCell(f.address).value;
     assert(value===null||typeof value==='number'||typeof value?.formula==='string');
     if(value?.formula)assert.equal(evaluate(sheet,f.address),value.result,`${name}/${block.name}/${f.name}`);
    }
   });
   if(name==='快速报价单'){
    const first=plan.blocks[0].fields[0],base=plan.blocks[0].fields.find(f=>f.name==='柜体');
    const original=evaluate(sheet,first.address);
    sheet.getCell(base.address).value+=100;
    assert.equal(evaluate(sheet,first.address),money(original+100),'formula responds to changed component');
   }
  }
 });
});

test('nine products and long attachment labels retain names, signed/zero values and distinct blocks',async()=>{
 const payload=structuredClone(fixture);
 const longName='长名称回归附件'.repeat(9);
 payload.items=Array.from({length:9},(_,i)=>{
  const item=structuredClone(fixture.items[0]);item.name=`第${i+1}项合成产品`;
  item.attachments=[{item_name:longName,quantity:1,quick_amount:i,formula_amount:i},
    {item_name:'标准安装板',category_level1:'安装板',attachment_price_sign:-1,quantity:1,quick_amount:-100,formula_amount:-50}];
  item.quick.attachment_fee=i-100;item.quick.total_cost=3150+i-100;return item;
 });
 await exported(payload,book=>{
  for(const name of ['公式法报价单','快速报价单']){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   assert.equal(plan.products.length,9);assert.equal(plan.blocks.length,9);
   plan.blocks.forEach((block,i)=>{
    const f=block.fields.find(f=>f.name===longName);assert(f);
    const last=endOfMerge(sheet,f.row,plan.first);
    let visiblePixels=0;for(let row=f.row;row<=last;row++)visiblePixels+=Math.round((sheet.getRow(row).height??15)*4/3);
    assert(visiblePixels>=Math.ceil((Math.ceil(longName.length*2/38)*12+2)*4/3),'long label has enough visible height, with or without a merge');
    const signed=block.fields.find(f=>f.name==='标准安装板');
    assert(sheet.getCell(signed.address).value<0);
    assert.equal(sheet.getCell(plan.products[i],2).text,`第${i+1}项合成产品`);
    for(const field of block.fields)if(sheet.getCell(field.address).value?.formula)
      assert.equal(evaluate(sheet,field.address),sheet.getCell(field.address).value.result);
   });
   assert.equal(sheet.getCell(plan.blocks[0].fields.find(f=>f.name===longName).address).value,0,'zero is not blank');
  }
 });
});

test('absent attachment values remain blank instead of being replaced by zero',async()=>{
 await exported(fixture,book=>{
  for(const name of ['公式法报价单','快速报价单']){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet);
   const row=plan.blocks[1].fields.find(f=>f.name==='接地线');assert(row);
   assert.equal(sheet.getCell(row.address).value,null);
  }
 });
});

test('multiline product and attachment names get enough vertical space without changing the quotation',async()=>{
 const payload=structuredClone(fixture);payload.items=[payload.items[0]];
 const item=payload.items[0];item.name='第一行合成产品名称\n第二行合成产品名称\n第三行合成产品名称';
 const label='第一行附件\n第二行附件\n第三行附件';
 item.attachments=[{item_name:label,quantity:1,quick_amount:50,formula_amount:50}];
 await exported(payload,book=>{
  for(const name of ['公式法报价单','快速报价单']){
   const sheet=book.getWorksheet(name),plan=quotationLayout(sheet),block=plan.blocks[0];
   assert.equal(sheet.getCell(plan.products[0],2).text,item.name);
   assert(block.name.endsWith(item.name));
   assert(endOfMerge(sheet,block.row,plan.first+1)>block.row);
   const field=block.fields.find(f=>f.name===label);assert(field);
   assert(height(sheet,field.row,endOfMerge(sheet,field.row,plan.first))>=38);
  }
 });
});
