import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const formulaSource=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/喷塑成本/JS,JP,JA,JE,JK,JM面积公式.xlsx';
const fixedSource=process.argv[3]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/喷塑成本/产品喷塑经验值表.xlsx';
const outDir=path.join(root,'database/cabinet-spray/generated');
const webDir=path.join(root,'database/cabinet-spray/web');
const text=value=>value==null?'':String(value).trim();
const positive=(value,label)=>{const n=Number(value);if(!Number.isFinite(n)||n<=0)throw new Error(`${label}必须为正数`);return n;};
const nonNegative=(value,label)=>{const n=Number(value);if(!Number.isFinite(n)||n<0)throw new Error(`${label}必须为非负数`);return n;};
const materialCodes=(value,label)=>{
  const material=text(value).toUpperCase();
  if(!material)return ['SECC'];
  if(material==='SECC')return ['SECC'];
  if(material==='SUS304/SUS316')return ['SUS304','SUS316'];
  throw new Error(`${label}材质无效：${value}`);
};
const normalizeFormula=value=>{
  let formula=text(value).replaceAll('（','(').replaceAll('）',')').replaceAll('高和宽的最小值','MIN(高度,宽度)');
  formula=formula.replaceAll('高度','__HEIGHT__').replaceAll('宽度','__WIDTH__').replaceAll('深度','__DEPTH__');
  formula=formula.replaceAll('高','高度').replaceAll('宽','宽度').replaceAll('深','深度');
  formula=formula.replaceAll('__HEIGHT__','高度').replaceAll('__WIDTH__','宽度').replaceAll('__DEPTH__','深度');
  parseFormula(formula);
  const variables=formulaVariables(formula);
  if(variables.some(v=>!['宽度','高度','深度'].includes(v)))throw new Error(`面积公式存在未知变量：${formula}`);
  return formula;
};
const quantityRule=value=>{
  if(typeof value==='number')return {kind:'CONSTANT',value:positive(value,'数量')};
  const normalized=text(value).replaceAll(' ','');
  if(/^\d+(?:\.\d+)?$/.test(normalized))return {kind:'CONSTANT',value:positive(normalized,'数量')};
  if(normalized==='350≤深度≤1000，高度＜1000，数量取1，否则数量取2')return {kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2};
  throw new Error(`不支持的喷塑数量规则：${value}`);
};
const layouts={
  JS:[{startCol:1,startRow:3,endRow:58,body:1.5,label:'标准箱体1.5'},{startCol:7,startRow:3,endRow:58,body:2,label:'箱体料厚改2'}],
  JP:[{startCol:1,startRow:3,endRow:48,body:null,label:'标准'}],
  JA:[{startCol:1,startRow:3,endRow:13,body:1.5,label:'标准箱体1.5'},{startCol:1,startRow:17,endRow:27,body:2,label:'箱体料厚改2'}],
  JE:[{startCol:1,startRow:3,endRow:13,body:null,label:'标准'}],
  JM:[{startCol:1,startRow:3,endRow:7,body:null,label:'标准'}],
  JK:[{startCol:1,startRow:3,endRow:8,body:null,label:'标准'}],
};

const formulaFile=await fs.promises.readFile(formulaSource);
const fixedFile=await fs.promises.readFile(fixedSource);
const formulaSha256=crypto.createHash('sha256').update(formulaFile).digest('hex');
const fixedSha256=crypto.createHash('sha256').update(fixedFile).digest('hex');
const sourceSha256=crypto.createHash('sha256').update(`FORMULA:${formulaSha256}\nFIXED:${fixedSha256}\n`).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(formulaFile);
const rules=[];const issues=[];
for(const [family,blocks] of Object.entries(layouts)){
  const sheet=workbook.getWorksheet(family);if(!sheet)throw new Error(`缺少工作表 ${family}`);
  for(const block of blocks){
    const starts=[];
    for(let row=block.startRow;row<=block.endRow;row++)if(text(sheet.getCell(row,block.startCol).value)==='单门/双门')starts.push(row);
    if(!starts.length)throw new Error(`${family} ${block.label} 未找到门型分组`);
    for(let index=0;index<starts.length;index++){
      const first=starts[index],last=(starts[index+1]??(block.endRow+1))-1;
      let door=null;
      for(let row=first;row<=last;row++){
        const value=text(sheet.getCell(row,block.startCol).value);
        if(/^\d+\/\d+$/.test(value)){door=value.split('/').map(Number);break;}
      }
      if(!door)throw new Error(`${family}!${first}:${last} 未找到门型数量`);
      for(let row=first;row<=last;row++){
        const values=Array.from({length:4},(_,i)=>sheet.getCell(row,block.startCol+i).value);
        if(!text(values[1]))continue;
        rules.push({family,body_thickness_profile_mm:block.body,profile_label:block.label,
          single_door_count:door[0],double_door_count:door[1],part_name:text(values[1]),
          area_formula:normalizeFormula(values[2]),quantity_rule:quantityRule(values[3]),
          source_sheet:family,source_row_no:row,source_column:block.startCol===1?'A:D':'G:J'});
      }
    }
  }
}

const fixedWorkbook=new ExcelJS.Workbook();await fixedWorkbook.xlsx.load(fixedFile);
const fixedConfigs={
  'JC（豪华型）':{product_code:'JC_EXP',profile_code:'LUXURY'},
  'JC（标配版）':{product_code:'JC_EXP',profile_code:'STANDARD'},
  JQ:{product_code:'JQ_EXP',profile_code:null},
  'JP超宽柜':{product_code:'JP_WIDE_EXP',profile_code:null},
  'JS超宽柜':{product_code:'JS_WIDE_EXP',profile_code:null},
  操作台:{product_code:'OP_TABLE_EXP',profile_code:null},
};
const fixedRules=[];
for(const [sheetName,config] of Object.entries(fixedConfigs)){
  const sheet=fixedWorkbook.getWorksheet(sheetName);if(!sheet)throw new Error(`缺少固定喷塑价格工作表 ${sheetName}`);
  for(let rowNo=3;rowNo<=sheet.rowCount;rowNo++){
    const model=text(sheet.getCell(rowNo,3).value);if(!model)continue;
    fixedRules.push({product_code:config.product_code,profile_code:config.profile_code,
      material_codes:materialCodes(sheet.getCell(rowNo,8).value,`${sheetName}!H${rowNo}`),model_code:model,
      width_mm:positive(sheet.getCell(rowNo,4).value,`${sheetName}!D${rowNo}`),
      height_mm:positive(sheet.getCell(rowNo,5).value,`${sheetName}!E${rowNo}`),
      depth_mm:positive(sheet.getCell(rowNo,6).value,`${sheetName}!F${rowNo}`),
      spray_cost:nonNegative(sheet.getCell(rowNo,7).value,`${sheetName}!G${rowNo}`),allow_dimension_scale:true,
      source_sheet:sheetName,source_row_no:rowNo});
  }
}
if(rules.length!==202)throw new Error(`喷塑面积规则应为 202 条，实际 ${rules.length}`);
if(fixedRules.length!==46)throw new Error(`固定喷塑价格应为 46 条，实际 ${fixedRules.length}`);
const fixedIdentities=new Set();
for(const rule of fixedRules){
  const key=[rule.product_code,rule.profile_code,rule.material_codes.join(','),rule.model_code,rule.width_mm,rule.height_mm,rule.depth_mm].join('|');
  if(fixedIdentities.has(key))throw new Error(`固定喷塑价格冲突：${key}`);
  fixedIdentities.add(key);
}

const identities=new Map();
for(const rule of rules){
  const key=[rule.family,rule.body_thickness_profile_mm??'通用',rule.single_door_count,rule.double_door_count,rule.part_name].join('|');
  const prior=identities.get(key);
  if(prior)issues.push({code:'DUPLICATE_PART_IN_SAME_VARIANT',message:'同一产品、料厚和门型中零件名称重复，会造成喷塑面积重复计费',
    key,first:`${prior.source_sheet}!${prior.source_column}${prior.source_row_no}`,second:`${rule.source_sheet}!${rule.source_column}${rule.source_row_no}`,
    first_formula:prior.area_formula,second_formula:rule.area_formula});
  else identities.set(key,rule);
}

const version=`cabinet-spray-${sourceSha256.slice(0,16)}-v2`;
const counts=Object.fromEntries(Object.keys(layouts).map(family=>[family,rules.filter(r=>r.family===family).length]));
const fixedCounts=Object.fromEntries([...new Set(fixedRules.map(r=>r.product_code))].map(code=>[code,fixedRules.filter(r=>r.product_code===code).length]));
const sourceFiles=[
  {kind:'AREA_FORMULA',name:path.basename(formulaSource),sha256:formulaSha256},
  {kind:'FIXED_PRICE',name:path.basename(fixedSource),sha256:fixedSha256},
];
const bundle={data_version:version,source_file:sourceFiles.map(x=>x.name).join('; '),source_sha256:sourceSha256,source_files:sourceFiles,rules,fixed_rules:fixedRules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'spray-audit.json'),JSON.stringify({version,sourceSha256,area_rules:rules.length,fixed_rules:fixedRules.length,counts,fixedCounts,issues},null,2)+'\n');
const oldBlocked=path.join(outDir,'cabinet-spray-bundle.blocked.json');if(fs.existsSync(oldBlocked))fs.unlinkSync(oldBlocked);
if(issues.length)fs.writeFileSync(oldBlocked,JSON.stringify(bundle,null,2)+'\n');
else {
  fs.writeFileSync(path.join(outDir,'cabinet-spray-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
  fs.copyFileSync(path.join(root,'database/migrations/cabinet_spray_v2.sql'),path.join(webDir,'01-create.sql'));
  const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
  fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- Combined SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_spray_catalog_v2(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
}
const report=[
  '# 完整柜体喷塑目录读取报告','',`- 数据版本：\`${version}\``,`- 合并源 SHA-256：\`${sourceSha256}\``,'',
  ...sourceFiles.map(x=>`- ${x.kind}：\`${x.name}\`（\`${x.sha256}\`）`),'',
  `- 面积公式规则：${rules.length}`,`- 固定/尺寸价格：${fixedRules.length}`,'',
  '## 面积公式覆盖','',
  ...Object.entries(counts).map(([family,count])=>`- ${family}：${count} 条`),'',
  '## 固定价格覆盖','',...Object.entries(fixedCounts).map(([code,count])=>`- ${code}：${count} 条`),'',
  '普通柜：每条明细面积 = 安全解析后的面积公式值 × 内部数量；总面积乘报价日当前喷塑单价。经验产品：按产品、JC配置、材质及尺寸匹配；标准尺寸精确命中，非标准尺寸沿用现有（宽+高+深）周长比例换算。选择“不喷塑”时两类成本均为 0。废料系数不参与喷塑计算。','',
  'JC 豪华型和标配版在源文件中的两个标准尺寸及金额完全相同，仍按两个独立配置保存来源。未标注材质的 JC 和 JP/JS 超宽柜按 SECC 导入；JQ 与操作台按源表区分 SECC 和 SUS304/SUS316。','',
  `导入状态：${issues.length?'BLOCKED':'READY'}`,'',
  ...(issues.length?issues.flatMap(issue=>[`- ${issue.message}`,`  - 首条：${issue.first}，公式 \`${issue.first_formula}\``,`  - 冲突：${issue.second}，公式 \`${issue.second_formula}\``]):['- 未发现阻断问题。']),''
].join('\n');
fs.writeFileSync(path.join(outDir,'读取报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,area_rules:rules.length,fixed_rules:fixedRules.length,counts,fixedCounts,issues},null,2));
