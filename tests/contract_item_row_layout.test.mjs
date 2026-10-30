import test from 'node:test';import assert from 'node:assert/strict';import {unzipSync,strFromU8} from 'fflate';import {DOMParser} from '@xmldom/xmldom';
import {inspectContractTemplate,renderContractTemplate} from '../api/contract_document.mjs';import {wrappedProductLines} from '../api/contract_item_row_layout.mjs';import {upperRmb} from '../api/contract_quote.mjs';
import {wordTemplate,excelTemplate,mapped,sampleQuote,sampleValues} from './helpers/contract_fixtures.mjs';
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',S='http://schemas.openxmlformats.org/spreadsheetml/2006/main';
function output(format,make,remarks){const b=make(),m=mapped(inspectContractTemplate(b,format),format);
 // The regression fixture has seven columns; explicitly map its content column to remarks.
 m.items.columns.remark=m.items.columns.specification;delete m.items.columns.specification;
 const items=remarks.map((remark,i)=>({...sampleQuote.items[i%2],number:i+1,name:'均高测试产品'+(i+1),remark}));const total=items.reduce((s,r)=>Math.round((s+r.total)*100)/100,0);return renderContractTemplate(b,format,m,{...sampleValues,total_amount:total,total_upper:upperRmb(total)},items);}
function heights(bytes,format){const z=unzipSync(bytes),doc=new DOMParser().parseFromString(strFromU8(z[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']),'application/xml'),ns=format==='docx'?W:S,tag=format==='docx'?'tr':'row';const rows=Array.from(doc.getElementsByTagNameNS(ns,tag)).filter(r=>r.textContent.includes('均高测试产品'));return rows.map(r=>format==='docx'?{value:Number(r.getElementsByTagNameNS(W,'trHeight')[0].getAttributeNS(W,'val'))/20,rule:r.getElementsByTagNameNS(W,'trHeight')[0].getAttributeNS(W,'hRule')}:{value:Number(r.getAttribute('ht')),rule:'content'});}
for(const [format,make] of [['docx',wordTemplate],['xlsx',excelTemplate]]){
 test(format+' mixed short, long and multiline notes use one height and grow or shrink with the contents',()=>{
  const short=heights(output(format,make,['灯1套','灯2套','灯3套']),format),long=heights(output(format,make,['灯1套','附件说明'.repeat(7),'接地线2根\n行程开关1只\n资料随货']),format);
  assert.equal(short.length,3);assert.equal(long.length,3);assert.equal(new Set(short.map(h=>h.value)).size,1);assert.equal(new Set(long.map(h=>h.value)).size,1);assert.ok(long[0].value>short[0].value);
  assert.equal(heights(output(format,make,['灯1套','灯2套','灯3套']),format)[0].value,short[0].value);
  if(format==='docx')assert.ok(long.every(h=>h.rule==='atLeast'));
 });
 test(format+' excessive contents fail clearly instead of clipping a completed contract',()=>assert.throws(()=>output(format,make,['非常长的备注'.repeat(2000)]),/备注.*高度|备注.*上限/));
}
test('width, explicit breaks and CJK or emoji affect wrapping',()=>{assert.ok(wrappedProductLines('附件规格数量'.repeat(6),45,11)>wrappedProductLines('附件规格数量'.repeat(6),160,11));assert.equal(wrappedProductLines('灯\n接地线\n',160,11),3);assert.ok(wrappedProductLines('🙂附件'.repeat(12),50,11)>1);});
test('Excel long uniform product rows get page breaks at complete row boundaries',()=>{const b=output('xlsx',excelTemplate,Array.from({length:25},(_,i)=>i===1?'附件说明'.repeat(7):'灯2套'));const files=unzipSync(b),doc=new DOMParser().parseFromString(strFromU8(files['xl/worksheets/sheet1.xml']),'application/xml');const breaks=Array.from(doc.getElementsByTagNameNS(S,'brk'));assert.ok(breaks.length>0);assert.ok(breaks.every(n=>Number(n.getAttribute('id'))>=9&&Number(n.getAttribute('id'))<33&&n.getAttribute('man')==='1'));assert.equal(new Set(heights(b,'xlsx').map(h=>h.value)).size,1);});
