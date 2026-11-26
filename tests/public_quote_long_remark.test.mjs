import test from 'node:test';
import assert from 'node:assert/strict';
import ExcelJS from '@excel.js/exceljs';
import {addPublicQuoteSheet,linkPublicQuoteSheet,verifyPublicQuoteSheet} from '../public_quote_sheet.mjs';

test('long customer remarks continue without text loss or duplicate prices',async()=>{
 const workbook=new ExcelJS.Workbook(),source=workbook.addWorksheet('报价');
 for(let c=1;c<=8;c++)source.getColumn(c).width=c===8?80:12;
 source.getCell('D1').value='LOCAL-LONG';
 const remark='柜体1分段板高度50 mm；玻璃门、内门和其它已选附件。\n'.repeat(100);
 for(let row=11;row<=12;row++){
  source.getCell(row,1).value=row-10;source.getCell(row,2).value='长备注测试柜';
  source.getCell(row,6).value=row===11?37845.64:54042.05;source.getCell(row,7).value=source.getCell(row,6).value;
  source.getCell(row,8).value=row===11?remark:'短备注';
 }
 source.getCell('G13').value=91887.69;source.mergeCells('A13:E13');source.getCell('A13').value='合计';
 const plan=addPublicQuoteSheet(workbook,source,2);
 linkPublicQuoteSheet(plan,source,new Map());
 verifyPublicQuoteSheet(workbook,plan);
 assert(plan.last>13);
 const remarkLinks=plan.links.filter(x=>x.source==='H11');
 assert(remarkLinks.length>1);assert.equal(remarkLinks.map(x=>x.result).join(''),remark);
 assert(plan.links.filter(x=>x.source==='F11').length===1);
 assert.equal(plan.links.find(x=>x.source==='G13').result,91887.69);
 for(let row=1;row<=plan.last;row++)assert((plan.sheet.getRow(row).height??15)<=409.5);
 const bytes=await workbook.xlsx.writeBuffer();
 const reread=new ExcelJS.Workbook();await reread.xlsx.load(bytes);
 assert.equal(reread.getWorksheet('报价2').getCell(remarkLinks[0].target).value.result,remarkLinks[0].result);
});

test('short remarks keep original public row addresses and links',()=>{
 const book=new ExcelJS.Workbook(),source=book.addWorksheet('报价');
 source.getCell('H11').value='原备注';source.getCell('F11').value=100;source.getCell('G12').value=100;
 const plan=addPublicQuoteSheet(book,source,1);linkPublicQuoteSheet(plan,source,new Map());
 assert.equal(plan.last,12);assert.equal(plan.sheet.getCell('H11').value.result,'原备注');
 assert.equal(plan.sheet.getCell('F11').value.formula,"'报价'!F11");verifyPublicQuoteSheet(book,plan);
});
