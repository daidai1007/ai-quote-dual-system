import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/辅材成本/辅材BOM清单.xlsx';
const outDir=path.join(root,'database/cabinet-auxiliary/generated');
const webDir=path.join(root,'database/cabinet-auxiliary/web');
const text=value=>value==null?'':String(value).trim();
const number=(value,label,{zero=false}={})=>{const n=Number(value);if(!Number.isFinite(n)||(zero?n<0:n<=0))throw new Error(`${label}无效`);return n;};
const formulaOf=cell=>cell.type===ExcelJS.ValueType.Formula?text(cell.formula):'';
const normalizeDimensionFormula=raw=>{
  let formula=text(raw).replaceAll('$','').replace(/^=/,'').replaceAll('A3','宽度').replaceAll('A5','高度').replaceAll('A7','深度');
  parseFormula(formula);const variables=formulaVariables(formula);
  if(variables.some(v=>!['宽度','高度','深度'].includes(v)))throw new Error(`辅材尺寸公式存在未知变量：${raw}`);
  return formula;
};
function resolveQuantity(sheet,rowNo,pieceCol,quantityCol,seen=new Set()){
  const cell=sheet.getCell(rowNo,quantityCol),value=cell.value;
  if(typeof value==='number')return {kind:'CONSTANT',value:number(value,`${sheet.name}!${cell.address}`,{zero:true})};
  const formula=formulaOf(cell).replaceAll('$','').replaceAll(' ','').toUpperCase();
  if(!formula){const n=Number(value);if(Number.isFinite(n))return {kind:'CONSTANT',value:number(n,`${sheet.name}!${cell.address}`,{zero:true})};throw new Error(`${sheet.name}!${cell.address} 数量为空`);}
  const direct=formula.match(/^([A-Z]+)(\d+)$/);
  if(direct){const address=direct[0];if(seen.has(address))throw new Error(`${sheet.name}!${cell.address} 数量循环引用`);seen.add(address);const ref=sheet.getCell(address);return resolveQuantity(sheet,ref.row,ref.col,ref.col,seen);}
  let match=formula.match(/^IF\(A5>800,1,0\)$/);if(match)return {kind:'HEIGHT_GT',threshold:800,when_true:1,when_false:0};
  match=formula.match(/^IF\(([A-Z]+\d+)>0,0,1\)$/);
  if(match){const ref=sheet.getCell(match[1]);const base=resolveQuantity(sheet,ref.row,ref.col,ref.col,seen);if(base.kind!=='HEIGHT_GT')throw new Error(`${sheet.name}!${cell.address} 反向数量条件不支持`);return {...base,when_true:0,when_false:1};}
  throw new Error(`${sheet.name}!${cell.address} 不支持的数量公式：${formula}`);
}
const sourceFile=await fs.promises.readFile(source);
const sourceSha256=crypto.createHash('sha256').update(sourceFile).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(sourceFile);
const profiles=[];const lines=[];const issues=[];
for(const sheet of workbook.worksheets){
  const isJP=sheet.name.startsWith('JP'),pieceCol=isJP?9:8,quantityCol=isJP?10:9,notesCol=isJP?11:10,priceCol=isJP?12:11,totalCol=isJP?13:12;
  const product=text(sheet.getCell(1,5).value)||(sheet.name.startsWith('JM')?'JM':'');
  if(!['JA','JE','JS','JP','JM'].includes(product))throw new Error(`${sheet.name} 产品代码无效：${product}`);
  let doorText=text(sheet.getCell(1,7).value);if(product==='JM')doorText=sheet.name.includes('双门')?'单门/双门0/1':'单门/双门1/0';
  const door=doorText.match(/单门\/双门(\d+)\/(\d+)/);if(!door)throw new Error(`${sheet.name} 门型无效：${doorText}`);
  const single=Number(door[1]),double=Number(door[2]),profileKey=`${product}:${single}/${double}`;
  const summary=sheet.getCell(1,3),summaryFormula=formulaOf(summary),expectedLast=Math.max(...Array.from({length:sheet.rowCount-2},(_,i)=>i+3).filter(r=>text(sheet.getCell(r,4).value)));
  const expectedRange=`${isJP?'M':'L'}3:${isJP?'M':'L'}${expectedLast}`;
  if(!summaryFormula.replaceAll('$','').toUpperCase().includes(expectedRange))issues.push(`${sheet.name}!C1 汇总范围 ${summaryFormula} 未覆盖 ${expectedRange}`);
  profiles.push({profile_key:profileKey,product_code:product,single_door_count:single,double_door_count:double,
    source_sheet:sheet.name,source_summary_formula:summaryFormula,source_cached_total:Number(summary.result??summary.value??0)});
  for(let rowNo=3;rowNo<=sheet.rowCount;rowNo++){
    const itemName=text(sheet.getCell(rowNo,4).value);if(!itemName)continue;
    const specCell=sheet.getCell(rowNo,6),lengthRaw=formulaOf(specCell),lengthFormula=lengthRaw?normalizeDimensionFormula(lengthRaw):null;
    const sprayCell=isJP?sheet.getCell(rowNo,7):null,sprayRaw=sprayCell?formulaOf(sprayCell):'';
    let sprayWidth=null;
    if(sprayRaw){const m=sprayRaw.replaceAll('$','').replaceAll(' ','').match(/^F\d+\*([0-9.]+)$/);if(!m)throw new Error(`${sheet.name}!${sprayCell.address} 不支持的喷塑面积公式：${sprayRaw}`);sprayWidth=number(m[1],`${sheet.name}!${sprayCell.address}`);}
    const totalCell=sheet.getCell(rowNo,totalCol),totalFormula=formulaOf(totalCell);
    const costKind=lengthFormula?(sprayRaw?'LENGTH_WITH_SPRAY':'LENGTH'):'UNIT';
    if(!totalFormula)throw new Error(`${sheet.name}!${totalCell.address} 缺少合计公式`);
    lines.push({profile_key:profileKey,line_no:Number(sheet.getCell(rowNo,2).value),item_code:text(sheet.getCell(rowNo,3).value)||null,
      item_name:itemName,spec_model:lengthFormula?null:(text(specCell.value)||null),material_name:text(sheet.getCell(rowNo,isJP?8:7).value)||null,
      quantity_rule:resolveQuantity(sheet,rowNo,pieceCol,quantityCol),unit_price:number(sheet.getCell(rowNo,priceCol).value,`${sheet.name}!${rowNo}单价`,{zero:true}),
      cost_kind:costKind,length_formula:lengthFormula,spray_width_m:sprayWidth,notes:text(sheet.getCell(rowNo,notesCol).value)||null,
      source_total_formula:totalFormula,source_cached_total:Number(totalCell.result??totalCell.value??0),source_sheet:sheet.name,source_row_no:rowNo});
  }
}
const profileKeys=new Set(profiles.map(p=>p.profile_key));if(profileKeys.size!==profiles.length)throw new Error('辅材门型配置重复');
if(issues.length)throw new Error(`辅材工作簿存在阻断问题：${issues.join('；')}`);
const version=`cabinet-auxiliary-${sourceSha256.slice(0,16)}-v1`;
const bundle={data_version:version,source_file:path.basename(source),source_sha256:sourceSha256,profiles,lines};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'cabinet-auxiliary-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
fs.copyFileSync(path.join(root,'database/migrations/cabinet_auxiliary_v1.sql'),path.join(webDir,'01-create.sql'));
const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_auxiliary_catalog_v1(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
const counts=Object.fromEntries([...new Set(profiles.map(p=>p.product_code))].map(p=>[p,lines.filter(l=>l.profile_key.startsWith(`${p}:`)).length]));
const report=['# 柜体辅材 BOM 读取报告','',`- 数据版本：\`${version}\``,`- 源文件 SHA-256：\`${sourceSha256}\``,`- 门型配置：${profiles.length}`,
  `- BOM 明细：${lines.length}`,'',...Object.entries(counts).map(([k,v])=>`- ${k}：${v} 条`),'',
  '宽度、高度、深度统一取当前程序报价行输入的柜体尺寸（mm）。源工作簿的 A3/A5/A7 仅是公式占位，不使用缓存值。动态长度小于 0 时按源 IF 公式取 0。JP 辅材框架喷塑面积按长度×0.198×内部数量，喷塑金额改用报价日当前喷塑单价；不喷塑为 0。','',
  '辅材成本和明细只替换公式法报价，快速报价不变。工作簿未提供 JK、JC、JQ、超宽柜及操作台辅材 BOM；这些产品暂时保留现有公式法辅材来源，不能将缺表解释为 0。','',
  '- 所有 16 张工作表的顶部汇总范围已覆盖全部实际 BOM 行。',''].join('\n');
fs.writeFileSync(path.join(outDir,'读取报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,profiles:profiles.length,lines:lines.length,counts,issues},null,2));
