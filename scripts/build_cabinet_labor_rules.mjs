import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/人工成本/人工公式xlsx.xlsx';
const outDir=path.join(root,'database/cabinet-labor/generated');
const webDir=path.join(root,'database/cabinet-labor/web');
const text=value=>value==null?'':String(value).trim();
const positive=(value,label,{zero=false}={})=>{const n=Number(value);if(!Number.isFinite(n)||(zero?n<0:n<=0))throw new Error(`${label}无效`);return n;};
const file=await fs.promises.readFile(source);
const sourceSha256=crypto.createHash('sha256').update(file).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(file);
const rules=[];const issues=[];
const formulas={JS:['安装纵梁','安装板'],JP:['安装纵梁','安装板'],JA:['安装板'],JE:['安装板'],JK:[],JM:[]};
for(const [family,excludedForStainless] of Object.entries(formulas)){
  const sheet=workbook.getWorksheet(family);if(!sheet)throw new Error(`缺少人工工作表 ${family}`);
  for(const rowNo of [3,4]){
    const materialText=text(sheet.getCell(rowNo,1).value),raw=text(sheet.getCell(rowNo,2).value);
    if(!materialText&&!raw)continue;
    for(let col=3;col<=5;col++)if(text(sheet.getCell(rowNo,col).value)!==raw)throw new Error(`${family}!${rowNo} 人工公式重复列不一致`);
    const normalized=raw.replaceAll('×','*').replaceAll(' ','');
    const match=normalized.match(/^人工=([0-9]+(?:\.[0-9]+)?)\+([0-9]+(?:\.[0-9]+)?)\*计价材料重量(?:（去掉(.+)的重量）)?$/);
    if(!match)throw new Error(`${family}!B${rowNo} 不支持的人工公式：${raw}`);
    const stainless=materialText==='SUS304/SUS316';
    if(!stainless&&materialText!=='SECC')throw new Error(`${family}!A${rowNo} 不支持的材质：${materialText}`);
    const exclusions=stainless?excludedForStainless:[];
    const sourceExclusion=text(match[3]);
    if((sourceExclusion?exclusions.join('和'):'')!==sourceExclusion)throw new Error(`${family}!B${rowNo} 扣除重量说明与已解析清单不一致`);
    rules.push({rule_kind:'LINEAR_WEIGHT',product_code:family,profile_code:null,
      material_codes:stainless?['SUS304','SUS316']:['SECC'],model_code:null,width_mm:null,height_mm:null,depth_mm:null,
      intercept:positive(match[1],`${family}!B${rowNo}截距`,{zero:true}),slope:positive(match[2],`${family}!B${rowNo}斜率`),
      excluded_part_names:exclusions,labor_cost:null,allow_dimension_scale:false,source_formula:raw,
      source_sheet:family,source_row_no:rowNo});
  }
}
const fixedSheets={
  'JC（豪华型）':{product:'JC_EXP',profile:'LUXURY'},'JC（标配型）':{product:'JC_EXP',profile:'STANDARD'},
  JQ:{product:'JQ_EXP',profile:null},'JP超宽柜':{product:'JP_WIDE_EXP',profile:null},
  'JS超宽柜':{product:'JS_WIDE_EXP',profile:null},'操作台':{product:'OP_TABLE_EXP',profile:null},
};
for(const [sheetName,config] of Object.entries(fixedSheets)){
  const sheet=workbook.getWorksheet(sheetName);if(!sheet)throw new Error(`缺少人工工作表 ${sheetName}`);
  for(let rowNo=3;rowNo<=sheet.rowCount;rowNo++){
    const model=text(sheet.getCell(rowNo,3).value);if(!model)continue;
    const materialText=text(sheet.getCell(rowNo,8).value),stainless=materialText==='SUS304/SUS316';
    if(!stainless&&materialText!=='SECC')throw new Error(`${sheetName}!H${rowNo} 不支持的材质：${materialText}`);
    rules.push({rule_kind:'FIXED',product_code:config.product,profile_code:config.profile,
      material_codes:stainless?['SUS304','SUS316']:['SECC'],model_code:model,
      width_mm:positive(sheet.getCell(rowNo,4).value,`${sheetName}!D${rowNo}`),
      height_mm:positive(sheet.getCell(rowNo,5).value,`${sheetName}!E${rowNo}`),
      depth_mm:positive(sheet.getCell(rowNo,6).value,`${sheetName}!F${rowNo}`),
      intercept:null,slope:null,excluded_part_names:[],labor_cost:positive(sheet.getCell(rowNo,7).value,`${sheetName}!G${rowNo}`,{zero:true}),
      allow_dimension_scale:true,source_formula:null,source_sheet:sheetName,source_row_no:rowNo});
  }
}
if(!rules.some(r=>r.product_code==='JM'&&r.material_codes.includes('SUS304')))
  issues.push('JM 工作表只有 SECC 人工公式；JM 选择 SUS304/SUS316 时服务端将返回具体缺规则错误。');
const identities=new Set();for(const rule of rules){const key=[rule.rule_kind,rule.product_code,rule.profile_code,rule.material_codes.join(','),rule.model_code,rule.width_mm,rule.height_mm,rule.depth_mm].join('|');if(identities.has(key))throw new Error(`人工规则冲突：${key}`);identities.add(key);}
const version=`cabinet-labor-${sourceSha256.slice(0,16)}-v1`;
const bundle={data_version:version,source_file:path.basename(source),source_sha256:sourceSha256,management_fee_rate:0.13,rules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'cabinet-labor-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
fs.copyFileSync(path.join(root,'database/migrations/cabinet_labor_v1.sql'),path.join(webDir,'01-create.sql'));
const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_labor_catalog_v1(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
const counts=Object.fromEntries([...new Set(rules.map(r=>r.product_code))].map(code=>[code,rules.filter(r=>r.product_code===code).length]));
const report=['# 柜体人工规则读取报告','',`- 数据版本：\`${version}\``,`- 源文件 SHA-256：\`${sourceSha256}\``,`- 规则总数：${rules.length}`,
  `- 线性重量规则：${rules.filter(r=>r.rule_kind==='LINEAR_WEIGHT').length}`,
  `- 固定/尺寸匹配规则：${rules.filter(r=>r.rule_kind==='FIXED').length}`,'',...Object.entries(counts).map(([k,v])=>`- ${k}：${v} 条`),'',
  '线性规则使用柜体“计价材料重量”。不锈钢 JS/JP 扣除安装纵梁和安装板的计价重量；不锈钢 JA/JE 扣除安装板的计价重量。固定表按产品、型号、材质及尺寸匹配，保留现有非标尺寸周长比例规则。人工与由人工派生的管理费只替换公式法报价，快速报价不变。','',
  '## 审计事项','',...issues.map(x=>`- ${x}`),''].join('\n');
fs.writeFileSync(path.join(outDir,'读取报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,total:rules.length,counts,issues},null,2));
