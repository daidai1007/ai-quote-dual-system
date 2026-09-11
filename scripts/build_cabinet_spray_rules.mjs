import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/喷塑成本/JS,JP,JA,JE,JK,JM面积公式.xlsx';
const outDir=path.join(root,'database/cabinet-spray/generated');
const webDir=path.join(root,'database/cabinet-spray/web');
const text=value=>value==null?'':String(value).trim();
const positive=(value,label)=>{const n=Number(value);if(!Number.isFinite(n)||n<=0)throw new Error(`${label}必须为正数`);return n;};
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

const file=await fs.promises.readFile(source);
const sourceSha256=crypto.createHash('sha256').update(file).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(file);
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

const identities=new Map();
for(const rule of rules){
  const key=[rule.family,rule.body_thickness_profile_mm??'通用',rule.single_door_count,rule.double_door_count,rule.part_name].join('|');
  const prior=identities.get(key);
  if(prior)issues.push({code:'DUPLICATE_PART_IN_SAME_VARIANT',message:'同一产品、料厚和门型中零件名称重复，会造成喷塑面积重复计费',
    key,first:`${prior.source_sheet}!${prior.source_column}${prior.source_row_no}`,second:`${rule.source_sheet}!${rule.source_column}${rule.source_row_no}`,
    first_formula:prior.area_formula,second_formula:rule.area_formula});
  else identities.set(key,rule);
}

const version=`cabinet-spray-${sourceSha256.slice(0,16)}-v1`;
const counts=Object.fromEntries(Object.keys(layouts).map(family=>[family,rules.filter(r=>r.family===family).length]));
const bundle={data_version:version,source_file:path.basename(source),source_sha256:sourceSha256,rules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'spray-audit.json'),JSON.stringify({version,sourceSha256,total:rules.length,counts,issues},null,2)+'\n');
const oldBlocked=path.join(outDir,'cabinet-spray-bundle.blocked.json');if(fs.existsSync(oldBlocked))fs.unlinkSync(oldBlocked);
if(issues.length)fs.writeFileSync(oldBlocked,JSON.stringify(bundle,null,2)+'\n');
else {
  fs.writeFileSync(path.join(outDir,'cabinet-spray-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
  fs.copyFileSync(path.join(root,'database/migrations/cabinet_spray_v1.sql'),path.join(webDir,'01-create.sql'));
  const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
  fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_spray_catalog_v1(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
}
const report=[
  '# 柜体喷塑面积规则读取报告','',`- 数据版本：\`${version}\``,`- 源文件 SHA-256：\`${sourceSha256}\``,
  `- 规则总数：${rules.length}`,`- 工作表：${Object.keys(layouts).join('、')}`,'',
  ...Object.entries(counts).map(([family,count])=>`- ${family}：${count} 条`),'',
  '计算口径：每条明细面积 = 安全解析后的面积公式值 × 内部数量；柜体喷塑总面积为全部适用明细之和；喷塑成本 = 柜体喷塑总面积 × 报价日当前喷塑单价。废料系数不参与喷塑计算。','',
  `导入状态：${issues.length?'BLOCKED':'READY'}`,'',
  ...(issues.length?issues.flatMap(issue=>[`- ${issue.message}`,`  - 首条：${issue.first}，公式 \`${issue.first_formula}\``,`  - 冲突：${issue.second}，公式 \`${issue.second_formula}\``]):['- 未发现阻断问题。']),''
].join('\n');
fs.writeFileSync(path.join(outDir,'读取报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,total:rules.length,counts,issues},null,2));
