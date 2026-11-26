// Customer-facing A4 sheet. All prices remain owned by the existing quote.
import {columnWidthPoints, fitWrappedTextRows, wrappedCellHeight} from './exceljs_range_adapter.mjs';

const clone=value=>value===undefined?undefined:structuredClone(value);
const plain=value=>value&&typeof value==='object'&&'formula'in value?(value.result??0):value;
const columnLetter=i=>String.fromCharCode(64+i);
const PUBLIC_REMARK_MAX_ROW_HEIGHT=300;
function splitRemark(text,width,fontSize){
 const parts=[];let start=0;
 while(start<text.length){
  let low=1,high=text.length-start,best=0;
  while(low<=high){
   const middle=Math.floor((low+high)/2);
   if(wrappedCellHeight(text.slice(start,start+middle),width,fontSize)<=PUBLIC_REMARK_MAX_ROW_HEIGHT){best=middle;low=middle+1;}
   else high=middle-1;
  }
  if(!best)throw new Error('备注列宽不足以显示文字');
  if(start+best<text.length&&/[\uD800-\uDBFF]/.test(text[start+best-1])&&/[\uDC00-\uDFFF]/.test(text[start+best]))best--;
  if(!best)throw new Error('备注列宽不足以显示完整字符');
  parts.push({text:text.slice(start,start+best),start,length:best});start+=best;
 }
 return parts.length?parts:[{text:'',start:0,length:0}];
}
function expandPublicRemarks(sheet,count){
 const width=columnWidthPoints(sheet.getColumn(8));
 const rows=Array.from({length:count+1},(_,i)=>{
  const logical=11+i;
  const cells=Array.from({length:8},(_,column)=>{const cell=sheet.getCell(logical,column+1);return{value:clone(cell.value),style:clone(cell.style)};});
  const text=String(plain(cells[7].value)??''),font=cells[7].style.font?.size??9;
  const chunks=i<count&&wrappedCellHeight(text,width,font)>409.5?splitRemark(text,width,font):null;
  return{logical,cells,height:sheet.getRow(logical).height,chunks};
 });
 const logicalRows=new Map(),targetRows=new Map(),slices=new Map();
 if(!rows.some(row=>row.chunks))return{last:11+count,physicalCount:count,targetRows,slices};
 const merges=sheet.model.merges.filter(range=>Number(/\d+$/.exec(range)[0])>=11);
 for(const range of merges)sheet.unMergeCells(range);
 sheet.spliceRows(11,count+1);
 let target=11;
 for(const row of rows){
  const chunks=row.chunks??[{text:String(plain(row.cells[7].value)??''),start:0,length:0}],first=target;
  for(const chunk of chunks){
   targetRows.set(target,row.logical);
   sheet.getRow(target).height=Math.min(row.height??15,PUBLIC_REMARK_MAX_ROW_HEIGHT);
   for(let column=1;column<=8;column++)sheet.getCell(target,column).style=clone(row.cells[column-1].style);
   if(row.chunks){sheet.getCell(target,8).value=chunk.text;slices.set(`H${target}`,chunk);}
   target++;
  }
  const last=target-1;logicalRows.set(row.logical,{first,last});
  for(let column=1;column<=8;column++){
   if(column===8&&row.chunks)continue;
   if(last>first)sheet.mergeCells(first,column,last,column);
   sheet.getCell(first,column).value=clone(row.cells[column-1].value);
  }
 }
 for(const range of merges){
  const [,a,r,b,s]=/^([A-H])(\d+):([A-H])(\d+)$/.exec(range);
  sheet.mergeCells(`${a}${logicalRows.get(Number(r)).first}:${b}${logicalRows.get(Number(s)).last}`);
 }
 return{last:target-1,physicalCount:target-12,targetRows,slices};
}
function fitPublicRows(sheet,count){
 for(let row=11;row<11+count;row++){
  for(let column=1;column<=8;column++){
   const cell=sheet.getCell(row,column);
   cell.alignment={...cell.alignment,wrapText:true,vertical:'middle'};
  }
 }
 fitWrappedTextRows(sheet,11,10+count);
 for(let row=4;row<=8;row++){
  let needed=sheet.getRow(row).height??16.5;
  for(const [first,last]of [[2,4],[6,8]]){
   const cell=sheet.getCell(row,first),width=Array.from({length:last-first+1},(_,i)=>columnWidthPoints(sheet.getColumn(first+i))).reduce((a,b)=>a+b,0);
   cell.alignment={...cell.alignment,wrapText:true,vertical:'middle'};
   needed=Math.max(needed,wrappedCellHeight(String(plain(cell.value)??''),width,cell.font?.size??10,2));
  }sheet.getRow(row).height=Math.ceil(needed*2)/2;
 }
 // Fit one page horizontally; preserve readable type and continue vertically.
 const printableWidth=595.28-36,printableHeight=841.89-36;
 const totalWidth=Array.from({length:8},(_,i)=>columnWidthPoints(sheet.getColumn(i+1))).reduce((a,b)=>a+b,0);
 const scale=Math.min(1,printableWidth/totalWidth),available=printableHeight/scale-6;
 let used=Array.from({length:10},(_,i)=>sheet.getRow(i+1).height??15).reduce((a,b)=>a+b,0);
 for(let row=11;row<=11+count;row++){
  const height=sheet.getRow(row).height??15;
  if(used+height>available){sheet.getRow(row-1).addPageBreak();used=sheet.getRow(10).height??33;}
  used+=height;
 }
}
export function addPublicQuoteSheet(workbook,source,count){
 const sheet=workbook.addWorksheet('报价2');sheet.views=[{showGridLines:false}];
 let last=11+count;
 const portraitWidths=[4,12,18,5,5,11,12,42];
 for(let column=1;column<=8;column++)sheet.getColumn(column).width=portraitWidths[column-1];
 for(let row=1;row<=last;row++){
  sheet.getRow(row).height=source.getRow(row).height;
  for(let column=1;column<=8;column++){
   const from=source.getCell(row,column),to=sheet.getCell(row,column);to.style=clone(from.style);
   if(!from.isMerged||from.master.address===from.address)to.value=clone(from.value);
  }
 }
 for(const range of source.model.merges){
  const match=/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(range);
  if(match&&match[1].length===1&&match[3].length===1&&match[3]<='H'&&Number(match[4])<=last)sheet.mergeCells(range);
 }
 // The old public source stores the quote id in D1. Give it the complete
 // merged value field in this new sheet so A4 output never clips the id.
 sheet.getCell('D1').value='编号';sheet.getCell('E1').value=plain(source.getCell('D1').value);
 for(let row=11;row<last;row++)sheet.getCell(row,8).font={...sheet.getCell(row,8).font,size:9};
 // The source reserves a 90-point audit subtotal row. The public print sheet
 // needs one readable total line, leaving A4 space for the product remarks.
 sheet.getRow(last).height=36;
 const expanded=expandPublicRemarks(sheet,count);last=expanded.last;
 fitPublicRows(sheet,expanded.physicalCount);
 sheet.pageSetup={paperSize:9,orientation:'portrait',fitToPage:true,fitToWidth:1,fitToHeight:0,
  horizontalCentered:true,verticalCentered:false,showGridLines:false,showRowColHeaders:false,
  margins:{left:.25,right:.25,top:.25,bottom:.25,header:.1,footer:.1},
  printArea:`A1:H${last}`,printTitlesRow:'10:10'};
 return {sheet,last,count,links:[],targetRows:expanded.targetRows,remarkSlices:expanded.slices};
}
export function linkPublicQuoteSheet(plan,source,sourceRows){
 const escaped=source.name.replaceAll("'","''"),sheet=plan.sheet;
 const link=(target,logicalAddress)=>{
  const [,column,row]=/^([A-H])(\d+)$/.exec(logicalAddress),address=column+(sourceRows.get(Number(row))?.first??Number(row));
  const from=source.getCell(address),value=plain(from.value),reference=`'${escaped}'!${address}`;
  const formula=typeof value==='number'?reference:`IF(${reference}="","",${reference})`;
  const slice=plan.remarkSlices?.get(target);
  const result=slice?slice.text:value??'';
  const linkedFormula=slice?`MID(${reference},${slice.start+1},${slice.length})`:formula;
  sheet.getCell(target).value={formula:linkedFormula,result};
  plan.links.push({target,source:address,formula:linkedFormula,result});
 };
 const blankContacts=new Set(['B4','B5','B6','B7','B8','F4','F5','F6','F7','F8']);
 for(let row=1;row<=plan.last;row++)for(let column=1;column<=8;column++){
  const cell=sheet.getCell(row,column),address=columnLetter(column)+row;
  if(cell.isMerged&&cell.master.address!==cell.address)continue;
  if(address==='D1'||address==='E1')continue;
  if(cell.value!==null&&cell.value!==undefined&&cell.value!==''||blankContacts.has(address))link(address,columnLetter(column)+(plan.targetRows?.get(row)??row));
 }
 link('E1','D1');
 return plan;
}
export function verifyPublicQuoteSheet(workbook,plan){
 const sheet=workbook.getWorksheet('报价2');
 if(!sheet||sheet.columnCount!==8||sheet.rowCount!==plan.last)throw new Error('报价2应仅包含完整的左侧报价单');
 for(const entry of plan.links){
  const value=sheet.getCell(entry.target).value;
  if(value?.formula!==entry.formula||JSON.stringify(value.result??(typeof entry.result==='number'?0:''))!==JSON.stringify(entry.result))throw new Error(`报价2联动校验失败：${entry.target}`);
 }
 if(sheet.pageSetup.paperSize!==9||sheet.pageSetup.orientation!=='portrait'||sheet.pageSetup.fitToWidth!==1||sheet.pageSetup.fitToHeight!==0||sheet.pageSetup.printArea!==`A1:H${plan.last}`)throw new Error('报价2 A4打印设置不完整');
 return {name:sheet.name,rows:plan.last,columns:8,linked_cells:plan.links.length,paper:'A4',orientation:'portrait'};
}
