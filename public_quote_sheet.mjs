// Customer-facing A4 sheet. All prices remain owned by the existing quote.
const clone=value=>value===undefined?undefined:structuredClone(value);
const plain=value=>value&&typeof value==='object'&&'formula'in value?(value.result??0):value;
const columnLetter=i=>String.fromCharCode(64+i);
const widthPoints=column=>(Math.floor((column.width??8.43)*7+5))*.75;
function linesFor(text,width,size){
 let lines=0;
 for(const line of String(text??'').replace(/\r\n?/g,'\n').split('\n')){
  let used=0,count=1;
  for(const character of line){
   const factor=/[\u2e80-\u9fff\uff00-\uffef]/u.test(character)?1.05:/[ilI.,:;!| ]/.test(character)?.4:/[0-9]/.test(character)?.63:.74;
   const advance=size*factor;
   if(used&&used+advance>width){count++;used=0;}used+=advance;
  }lines+=count;
 }return Math.max(1,lines);
}
function fitPublicRows(sheet,count){
 for(let row=11;row<11+count;row++){
  const target=sheet.getRow(row);let needed=target.height??18;
  for(let column=1;column<=8;column++){
   const cell=target.getCell(column),size=cell.font?.size??10;
   needed=Math.max(needed,linesFor(plain(cell.value),Math.max(12,widthPoints(sheet.getColumn(column))-9)*.92,size)*size*1.4+8);
   cell.alignment={...cell.alignment,wrapText:true,vertical:'middle'};
  }
  if(needed>409.5)throw new Error(`报价2第${row-10}项备注或规格过长，超过Excel单行可打印高度，请分段整理说明后导出。`);
  target.height=Math.ceil(needed*2)/2;
 }
 for(let row=4;row<=8;row++){
  let needed=sheet.getRow(row).height??16.5;
  for(const [first,last]of [[2,4],[6,8]]){
   const cell=sheet.getCell(row,first),width=Array.from({length:last-first+1},(_,i)=>widthPoints(sheet.getColumn(first+i))).reduce((a,b)=>a+b,0);
   cell.alignment={...cell.alignment,wrapText:true,vertical:'middle'};
   needed=Math.max(needed,linesFor(plain(cell.value),(width-9)*.92,cell.font?.size??10)*(cell.font?.size??10)*1.4+2);
  }sheet.getRow(row).height=Math.ceil(needed*2)/2;
 }
 // Fit one page horizontally; preserve readable type and continue vertically.
 const printableWidth=595.28-36,printableHeight=841.89-36;
 const totalWidth=Array.from({length:8},(_,i)=>widthPoints(sheet.getColumn(i+1))).reduce((a,b)=>a+b,0);
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
 const last=11+count;
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
 sheet.mergeCells('D3:E3');
 sheet.getCell('F3').value=plain(source.getCell('E3').value);
 sheet.getCell('D3').alignment={...sheet.getCell('D3').alignment,horizontal:'center'};
 sheet.getCell('F3').alignment={...sheet.getCell('F3').alignment,horizontal:'center'};
 for(let row=11;row<last;row++)sheet.getCell(row,8).font={...sheet.getCell(row,8).font,size:9};
 // The source reserves a 90-point audit subtotal row. The public print sheet
 // needs one readable total line, leaving A4 space for the product remarks.
 sheet.getRow(last).height=36;
 fitPublicRows(sheet,count);
 sheet.pageSetup={paperSize:9,orientation:'portrait',fitToPage:true,fitToWidth:1,fitToHeight:0,
  horizontalCentered:true,verticalCentered:false,showGridLines:false,showRowColHeaders:false,
  margins:{left:.25,right:.25,top:.25,bottom:.25,header:.1,footer:.1},
  printArea:`A1:H${last}`,printTitlesRow:'10:10'};
 return {sheet,last,count,links:[]};
}
export function linkPublicQuoteSheet(plan,source,sourceRows){
 const escaped=source.name.replaceAll("'","''"),sheet=plan.sheet;
 const link=(target,logicalAddress)=>{
  const [,column,row]=/^([A-H])(\d+)$/.exec(logicalAddress),address=column+(sourceRows.get(Number(row))?.first??Number(row));
  const from=source.getCell(address),value=plain(from.value),reference=`'${escaped}'!${address}`;
  const formula=typeof value==='number'?reference:`IF(${reference}="","",${reference})`;
  const result=value??'';sheet.getCell(target).value={formula,result};
  plan.links.push({target,source:address,formula,result});
 };
 const blankContacts=new Set(['B4','B5','B6','B7','B8','F4','F5','F6','F7','F8']);
 for(let row=1;row<=plan.last;row++)for(let column=1;column<=8;column++){
  const cell=sheet.getCell(row,column),address=columnLetter(column)+row;
  if(cell.isMerged&&cell.master.address!==cell.address)continue;
  if(address==='D1'||address==='E1'||address==='F3')continue;
  if(cell.value!==null&&cell.value!==undefined&&cell.value!==''||blankContacts.has(address))link(address,address);
 }
 link('E1','D1');
 link('F3','E3');
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
