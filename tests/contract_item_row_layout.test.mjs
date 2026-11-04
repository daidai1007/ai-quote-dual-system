import test from 'node:test';import assert from 'node:assert/strict';import {unzipSync,zipSync,strFromU8,strToU8} from 'fflate';import {DOMParser} from '@xmldom/xmldom';
import {inspectContractTemplate,renderContractTemplate} from '../api/contract_document.mjs';import {wrappedProductLines} from '../api/contract_item_row_layout.mjs';import {upperRmb} from '../api/contract_quote.mjs';
import {wordTemplate,excelTemplate,mapped,sampleQuote,sampleValues} from './helpers/contract_fixtures.mjs';
import {ledgerExcelTemplate} from './helpers/contract_ledger_fixtures.mjs';
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',S='http://schemas.openxmlformats.org/spreadsheetml/2006/main';
function output(format,make,remarks){const b=make(),m=mapped(inspectContractTemplate(b,format),format);
 // The regression fixture has seven columns; explicitly map its content column to remarks.
 m.items.columns.remark=m.items.columns.specification;delete m.items.columns.specification;
 const items=remarks.map((remark,i)=>({...sampleQuote.items[i%2],number:i+1,name:'均高测试产品'+(i+1),remark}));const total=items.reduce((s,r)=>Math.round((s+r.total)*100)/100,0);return renderContractTemplate(b,format,m,{...sampleValues,total_amount:total,total_upper:upperRmb(total)},items);}
function heights(bytes,format){const z=unzipSync(bytes),doc=new DOMParser().parseFromString(strFromU8(z[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']),'application/xml'),ns=format==='docx'?W:S,tag=format==='docx'?'tr':'row';const rows=Array.from(doc.getElementsByTagNameNS(ns,tag)).filter(r=>r.textContent.includes('均高测试产品'));return rows.map(r=>format==='docx'?{value:Number(r.getElementsByTagNameNS(W,'trHeight')[0].getAttributeNS(W,'val'))/20,rule:r.getElementsByTagNameNS(W,'trHeight')[0].getAttributeNS(W,'hRule')}:{value:Number(r.getAttribute('ht')),rule:'content'});}
test('Word product rows replace the template fixed height with natural text height',()=>{
 const fixedTemplate=()=>{
  const z=unzipSync(wordTemplate()),part='word/document.xml';
  z[part]=strToU8(strFromU8(z[part]).replace(/<w:tr>[\s\S]*?<\/w:tr>/g,row=>row.includes('{{item.name}}')?row.replace('<w:trPr>','<w:trPr><w:trHeight w:val="2400" w:hRule="exact"/>'):row));
  return zipSync(z);
 };
 const result=heights(output('docx',fixedTemplate,['灯1套','附件说明'.repeat(7)]),'docx');
 assert.deepEqual(result,[{value:0,rule:'auto'},{value:0,rule:'auto'}]);
});
test('Excel measures each product row independently and keeps short rows compact',()=>{
 const short=heights(output('xlsx',excelTemplate,['灯1套']),'xlsx');
 const mixed=heights(output('xlsx',excelTemplate,['灯1套','附件说明'.repeat(7),'接地线2根\n行程开关1只\n资料随货','灯1套']),'xlsx');
 assert.equal(mixed.length,4);assert.equal(mixed[0].value,short[0].value);assert.equal(mixed[3].value,short[0].value);
 assert.ok(short[0].value<=20);assert.ok(mixed[1].value>short[0].value);assert.ok(mixed[2].value>short[0].value);
});
test('Word excessive content fails instead of clipping',()=>assert.throws(()=>output('docx',wordTemplate,['非常长的备注'.repeat(2000)]),/备注.*高度/));
test('Excel excessive content identifies the product row and exact cell',()=>assert.throws(()=>output('xlsx',excelTemplate,['短备注','非常长的备注'.repeat(2000)]),/第 2 条产品明细（C10 单元格）.*409\.5/));
test('Excel permits a complete four-line remark at 72 points without overestimating it',()=>{
 const z=unzipSync(ledgerExcelTemplate()),sheet='xl/worksheets/sheet1.xml',styles='xl/styles.xml';
 z[sheet]=strToU8(strFromU8(z[sheet]).replace('max="8" width="26"','max="8" width="201.641666666667"').replace('<c r="H9" s="1"','<c r="H9" s="3"'));
 z[styles]=strToU8(strFromU8(z[styles]).replace('<fonts count="1">','<fonts count="2">').replace('</fonts>','<font><sz val="72"/><name val="宋体"/></font></fonts>').replace('<cellXfs count="3">','<cellXfs count="4">').replace('</cellXfs>','<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf></cellXfs>'));
 const bytes=zipSync(z),remark='附件按图制作'.repeat(7),items=sampleQuote.items.map((item,i)=>({...item,remark:i?remark:'短备注'}));
 const result=unzipSync(renderContractTemplate(bytes,'xlsx',inspectContractTemplate(bytes,'xlsx').suggested,sampleValues,items));
 const doc=new DOMParser().parseFromString(strFromU8(result[sheet]),'application/xml');
 const cell=Array.from(doc.getElementsByTagNameNS(S,'c')).find(c=>c.getAttribute('r')==='H10');
 assert.equal(cell.textContent,remark);assert.equal(Number(cell.parentNode.getAttribute('ht')),361.5);
});
test('width, explicit breaks and CJK or emoji affect wrapping',()=>{assert.ok(wrappedProductLines('附件规格数量'.repeat(6),45,11)>wrappedProductLines('附件规格数量'.repeat(6),160,11));assert.equal(wrappedProductLines('灯\n接地线\n',160,11),3);assert.ok(wrappedProductLines('🙂附件'.repeat(12),50,11)>1);});
test('Latin identifiers move to the next line as a unit when they fit there',()=>{
 assert.equal(wrappedProductLines('ABCD EFGH JKLM NOPQ RSTU',50,10),5);
});
test('Excel paginates mixed-height rows on complete row boundaries',()=>{
 const b=output('xlsx',excelTemplate,Array.from({length:70},(_,i)=>i%7===0?'附件说明'.repeat(9):'灯2套'));
 const files=unzipSync(b),doc=new DOMParser().parseFromString(strFromU8(files['xl/worksheets/sheet1.xml']),'application/xml');
 const breaks=Array.from(doc.getElementsByTagNameNS(S,'brk'));assert.ok(breaks.length>0);
 assert.ok(breaks.every(n=>Number(n.getAttribute('id'))>=9&&Number(n.getAttribute('id'))<78&&n.getAttribute('man')==='1'));
 assert.ok(new Set(heights(b,'xlsx').map(h=>h.value)).size>1);
});
