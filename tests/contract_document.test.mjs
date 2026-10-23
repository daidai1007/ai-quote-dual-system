import test from 'node:test';import assert from 'node:assert/strict';import {unzipSync,strFromU8,zipSync,strToU8} from 'fflate';
import {inspectContractTemplate,renderContractTemplate,validateContractMapping} from '../api/contract_document.mjs';
import {contractQuote,upperRmb} from '../api/contract_quote.mjs';
import {wordTemplate,excelTemplate,sampleQuote,sampleValues,mapped} from './helpers/contract_fixtures.mjs';
for(const [format,make] of [['docx',wordTemplate],['xlsx',excelTemplate]])test(format+' replaces only configured fields, expands products and preserves formatting',()=>{
 const before=make(),inspection=inspectContractTemplate(before,format),mapping=mapped(inspection,format);
 assert.ok(mapping.items);assert.ok(mapping.fields.some(f=>f.source==='buyer_name'));
 const result=renderContractTemplate(before,format,mapping,sampleValues,sampleQuote.items),files=unzipSync(result);
 const main=strFromU8(files[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);
 assert.match(main,/本机测试客户 A/);assert.match(main,/本机回归柜甲/);assert.match(main,/本机回归柜乙/);assert.match(main,/500/);assert.doesNotMatch(main,/\{\{/);
 if(format==='docx'){assert.match(strFromU8(files['word/header1.xml']),/人工模板页眉/);assert.match(main,/w:tblHeader/);assert.match(main,/供方签章/);}
 else{assert.match(main,/SUM\(G9:G10\)/);assert.match(main,/<v>650\.3<\/v>/);assert.match(main,/A11:F11/);assert.match(strFromU8(files['xl/workbook.xml']),/\$G\$14/);assert.match(strFromU8(files['xl/worksheets/sheet2.xml']),/'合同'!G11/);assert.deepEqual(files['xl/styles.xml'],unzipSync(before)['xl/styles.xml']);}
});
test('ambiguous mappings, unknown fields, unsupported formulas and malicious packages fail explicitly',()=>{
 const bytes=wordTemplate(),i=inspectContractTemplate(bytes,'docx'),m=mapped(i,'docx');
 assert.throws(()=>validateContractMapping(bytes,'docx',{...m,fields:[...m.fields,m.fields[0]]}),/重复/);
 assert.throws(()=>renderContractTemplate(bytes,'docx',m,{...sampleValues,seller_name:''},sampleQuote.items),/补齐/);
 const files=unzipSync(excelTemplate());files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace('ROUND(SUM(G9:G9),2)','WEBSERVICE("http://invalid")'));
 const unsafe=Buffer.from(zipSync(files));assert.throws(()=>renderContractTemplate(unsafe,'xlsx',mapped(inspectContractTemplate(unsafe,'xlsx'),'xlsx'),sampleValues,sampleQuote.items),/不支持/);
 assert.throws(()=>inspectContractTemplate(Buffer.from('not-office'),'docx'));
 const external=unzipSync(wordTemplate());external['word/_rels/document.xml.rels']=strToU8('<Relationships><Relationship TargetMode="External" Target="file:///private"/></Relationships>');assert.throws(()=>inspectContractTemplate(Buffer.from(zipSync(external)),'docx'),/外部链接/);
 const active=unzipSync(wordTemplate());active['word/document.xml']=strToU8(strFromU8(active['word/document.xml']).replace('</w:body>','<w:p><w:fldSimple w:instr="DDEAUTO LOCAL TEST"/></w:p></w:body>'));assert.throws(()=>inspectContractTemplate(Buffer.from(zipSync(active)),'docx'),/外部动态域/);
});
test('exact quote arithmetic, method selection and uppercase do not consult current prices',()=>{
 const snapshot={draft_items:[{formula:{material_cost:10,auxiliary_cost:2,labor_cost:3,spray_cost:1,management_fee:.96},formula_discount:.8,freight_fee:5,attachments:[],quote_display:{name:'本机柜',quantity:2,unit_price:175,total:350}}]};
 assert.equal(contractQuote(snapshot,'QUICK').total,350);assert.equal(contractQuote(snapshot,'FORMULA').total,37.14);
 assert.throws(()=>contractQuote(snapshot,''),/请选择/);assert.throws(()=>contractQuote({draft_items:[{quote_display:{quantity:2,unit_price:1,total:3}}]},'QUICK'),/不一致/);
 assert.equal(upperRmb(128600),'壹拾贰万捌仟陆佰元整');assert.equal(upperRmb(120600),'壹拾贰万零陆佰元整');assert.equal(upperRmb(0),'零元整');assert.equal(upperRmb(.05),'零元伍分');assert.equal(upperRmb(650.3),'陆佰伍拾元叁角');
});

test('formula strings, shared strings, totals and unrelated sheet drawings are handled deliberately',()=>{
 const files=unzipSync(excelTemplate());
 const sheet2=strFromU8(files['xl/worksheets/sheet2.xml']).replace('</sheetData>','<row r="2"><c r="A2" t="str"><f>IF(1=1,"G10",0)</f><v>old</v></c></row></sheetData>');
 files['xl/worksheets/sheet2.xml']=strToU8(sheet2);
 const drawing='<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"><xdr:twoCellAnchor><xdr:from><xdr:row>20</xdr:row></xdr:from></xdr:twoCellAnchor></xdr:wsDr>';
 files['xl/drawings/drawing2.xml']=strToU8(drawing);
 const before=Buffer.from(zipSync(files));const result=unzipSync(renderContractTemplate(before,'xlsx',mapped(inspectContractTemplate(before,'xlsx'),'xlsx'),sampleValues,sampleQuote.items));
 assert.match(strFromU8(result['xl/worksheets/sheet2.xml']),/"G10"/);assert.deepEqual(result['xl/drawings/drawing2.xml'],files['xl/drawings/drawing2.xml']);
 files['xl/sharedStrings.xml']=strToU8('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>{{unknown_field}}</t></si></sst>');
 files['xl/worksheets/sheet2.xml']=strToU8(sheet2.replace('</sheetData>','<row r="3"><c r="A3" t="s"><v>0</v></c></row></sheetData>'));
 const missing=Buffer.from(zipSync(files));const mapping=mapped(inspectContractTemplate(missing,'xlsx'),'xlsx');mapping.fields=mapping.fields.filter(f=>f.source!=='custom:unknown_field');
 assert.throws(()=>renderContractTemplate(missing,'xlsx',mapping,sampleValues,sampleQuote.items),/未填字段/);
 const wrong=unzipSync(excelTemplate());wrong['xl/worksheets/sheet1.xml']=strToU8(strFromU8(wrong['xl/worksheets/sheet1.xml']).replace('ROUND(SUM(G9:G9),2)','ROUND(SUM(G9:G9),2)+1'));
 const wrongBytes=Buffer.from(zipSync(wrong));assert.throws(()=>renderContractTemplate(wrongBytes,'xlsx',mapped(inspectContractTemplate(wrongBytes,'xlsx'),'xlsx'),sampleValues,sampleQuote.items),/总额不一致/);
});

test('large product sets remain complete and Office formula caches never reuse stale totals',()=>{
 const items=Array.from({length:120},(_,i)=>({...sampleQuote.items[i%2],number:i+1,name:'多页本机产品'+(i+1)}));const total=items.reduce((s,r)=>Math.round((s+r.total)*100)/100,0);
 for(const [format,make]of [['docx',wordTemplate],['xlsx',excelTemplate]]){
  const before=make();const result=unzipSync(renderContractTemplate(before,format,mapped(inspectContractTemplate(before,format),format),{...sampleValues,total_amount:total,total_upper:upperRmb(total)},items));
  const text=strFromU8(result[format==='docx'?'word/document.xml':'xl/worksheets/sheet1.xml']);assert.match(text,/多页本机产品120/);assert.doesNotMatch(text,/99999/);assert.match(text,/39018/);
 }
});

test('unformatted Excel blanks can be mapped, merged interiors and invalid addresses cannot',()=>{
 const files=unzipSync(excelTemplate());files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace(/<c r="B3".*?<\/c>/s,''));
 const bytes=Buffer.from(zipSync(files)),mapping=mapped(inspectContractTemplate(bytes,'xlsx'),'xlsx');mapping.fields.push({source:'buyer_name',target:'xl/worksheets/sheet1.xml#B3',find:''});
 mapping.fields.push({source:'custom:备注',target:'xl/worksheets/sheet1.xml#D6',find:''});
 const rendered=unzipSync(renderContractTemplate(bytes,'xlsx',mapping,{...sampleValues,'custom:备注':'第一行\n第二行'},sampleQuote.items));const text=strFromU8(rendered['xl/worksheets/sheet1.xml']);assert.match(text,/本机测试客户 A/);assert.match(text,/r="D6"/);assert.match(text,/第二行/);
 for(const address of ['C3','XFE1','B1048577','B3#alias'])assert.throws(()=>validateContractMapping(bytes,'xlsx',{...mapping,fields:mapping.fields.map(f=>f.source==='buyer_name'?{...f,target:'xl/worksheets/sheet1.xml#'+address}:f)}));
});

test('multiple scalar replacements in one Excel cell use literal text; Word multiline keeps breaks',()=>{
 const files=unzipSync(excelTemplate());files['xl/worksheets/sheet1.xml']=strToU8(strFromU8(files['xl/worksheets/sheet1.xml']).replace('{{buyer_name}}','{{buyer_name}} / {{seller_name}}'));
 const bytes=Buffer.from(zipSync(files));const output=unzipSync(renderContractTemplate(bytes,'xlsx',mapped(inspectContractTemplate(bytes,'xlsx'),'xlsx'),{...sampleValues,buyer_name:'literal $& buyer'},sampleQuote.items));const text=strFromU8(output['xl/worksheets/sheet1.xml']);assert.match(text,/literal \$&amp; buyer \/ 本机测试供方/);assert.doesNotMatch(text,/\{\{/);
 const word=wordTemplate();const document=unzipSync(renderContractTemplate(word,'docx',mapped(inspectContractTemplate(word,'docx'),'docx'),{...sampleValues,seller_name:'第一行\n第二行'},sampleQuote.items));assert.match(strFromU8(document['word/document.xml']),/<w:br\/>/);
});
