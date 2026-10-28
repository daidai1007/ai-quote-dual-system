// Read the saved physical cells without relying on the production layout map.
// Legacy price-rule tests use the logical projection below; actual formatting,
// geometry and moved references are tested against the saved physical workbook.
import assert from 'node:assert/strict';

const clone=value=>value===undefined?undefined:structuredClone(value);
const letter=number=>{let s='';for(let n=number;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
export function quotationLayout(sheet){
 const first=sheet.name==='公式法报价单'?12:10;
 if(sheet.getCell(10,first).text!=='项目')return null;
 const products=[],blocks=[];let subtotal;
 const master=cell=>!cell.isMerged||cell.master.address===cell.address;
 sheet.eachRow({includeEmpty:false},row=>{
  const serial=row.getCell(1),name=row.getCell(2);
  if(row.number>=11&&master(serial)&&typeof serial.value==='number'&&serial.value>0)products.push(row.number);
  if(master(name)&&name.text==='合计')subtotal=row.number;
 });
 const valueColumns=Array.from({length:sheet.columnCount-first},(_,i)=>first+1+i)
  .filter(column=>/^\d+ · /.test(sheet.getCell(10,column).text));
 if(valueColumns.length===products.length){
  for(const column of valueColumns)blocks.push({row:10,name:sheet.getCell(10,column).text,column,fields:[]});
  sheet.eachRow({includeEmpty:false},row=>{
   const label=row.getCell(first);
   if(row.number<=10||!master(label)||!label.text||label.text==='项目')return;
   for(const block of blocks){
    const value=row.getCell(block.column);
    block.fields.push({name:label.text,row:row.number,label:label.address,address:value.address,value:clone(value.value)});
   }
  });
  assert(subtotal,'public subtotal is present');
  return {first,products,subtotal,blocks,layout:'matrix'};
 }
 sheet.eachRow({includeEmpty:false},row=>{
  const serial=row.getCell(1),name=row.getCell(2),label=row.getCell(first),value=row.getCell(first+1);
  if(!master(label))return;
  if(label.text==='项目'&&typeof value.value==='string'&&/^\d+ · /.test(value.text)){
   blocks.push({row:row.number,name:value.text,fields:[]});
  }else if(row.number>10&&label.text&&blocks.length){
   blocks.at(-1).fields.push({name:label.text,row:row.number,label:label.address,address:value.address,value:clone(value.value)});
  }
 });
 assert.equal(products.length,blocks.length,'one detail block per public product');
 assert(subtotal,'public subtotal is present');
 return {first,products,subtotal,blocks,layout:'stacked'};
}

export function publicQuotationCell(sheet,logicalAddress){
 const plan=quotationLayout(sheet);if(!plan)return sheet.getCell(logicalAddress);
 const [,column,sourceRow]=/^([A-H])(\d+)$/.exec(logicalAddress);
 const row=Number(sourceRow);
 return sheet.getCell(`${column}${row<11?row:plan.products[row-11]??(row===11+plan.products.length?plan.subtotal:row)}`);
}

export function projectQuotationAudit(workbook){
 for(const name of ['公式法报价单','快速报价单']){
  const sheet=workbook.getWorksheet(name);if(!sheet)continue;
  const plan=quotationLayout(sheet);if(!plan)continue;
  const cells=[],addresses=new Map();
  const rows=[...plan.products,plan.subtotal];
  rows.forEach((physical,index)=>{
   for(let c=1;c<=8;c++){
    const cell=sheet.getCell(physical,c),address=`${letter(c)}${11+index}`;
    cells.push({address,value:clone(cell.value),style:clone(cell.style)});
    addresses.set(cell.address,address);
   }
  });
  plan.blocks.forEach((block,index)=>block.fields.forEach((field,ordinal)=>{
   const address=`${letter(plan.first+ordinal)}${11+index}`;
   addresses.set(field.address,address);
   cells.push({address,value:clone(field.value)});
  }));
  // Rewrite position only, never an amount, operator, factor or rounding rule.
  const remap=formula=>formula.replace(/\$?([A-Z]{1,3})\$?([1-9]\d*)\b/g,(match,c,r)=>addresses.get(c+r)||match);
  for(const merge of [...sheet.model.merges])if(Number(/\d+$/.exec(merge)[0])>=11)sheet.unMergeCells(merge);
  sheet.spliceRows(11,sheet.rowCount-10);
  for(let row=1;row<=10;row++)for(let column=9;column<=sheet.columnCount;column++)sheet.getCell(row,column).value=null;
  plan.blocks[0].fields.forEach((f,i)=>{sheet.getCell(10,plan.first+i).value=f.name;});
  for(const saved of cells){
   const value=saved.value;
   sheet.getCell(saved.address).value=value?.formula?{...value,formula:remap(value.formula)}:value;
   if(saved.style)sheet.getCell(saved.address).style=saved.style;
  }
 }
 return workbook;
}
