import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const formulaSource=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/材料重量/JS,JP,JA,JE,JK,JM材料明细-面积公式.xlsx';
const fixedSource=process.argv[3]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/材料重量/JC,JQ,JP超宽，JS超宽，操作台重量表.xlsx';
const outDir=path.join(root,'database/cabinet-material/generated');
const webDir=path.join(root,'database/cabinet-material/web');
const text=value=>value==null?'':String(value).trim();
const number=(value,label)=>{const n=Number(value);if(!Number.isFinite(n)||n<=0)throw new Error(`${label}必须为正数`);return n;};
const materialCodes=(value,label)=>{
  const material=text(value).toUpperCase();
  if(!material||material==='SECC')return ['SECC'];
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
  if(typeof value==='number')return {kind:'CONSTANT',value:number(value,'数量')};
  const normalized=text(value).replaceAll(' ','');
  if(/^\d+(?:\.\d+)?$/.test(normalized))return {kind:'CONSTANT',value:number(normalized,'数量')};
  if(normalized==='350≤深度≤1000，高度＜1000，数量取1，否则数量取2')return {kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2};
  if(normalized==='高度＞1000，数量取1，否则为0')return {kind:'HEIGHT_GT',threshold:1000,when_true:1,when_false:0};
  if(normalized==='宽度＞600且高度＞1000或者宽度＞800且高度＞600，数量为2，否则为0')return {kind:'JE_REINFORCEMENT',when_true:2,when_false:0};
  throw new Error(`不支持的数量规则：${value}`);
};
const layouts={
  JS:[{startCol:1,startRow:3,endRow:70,body:1.5,label:'标准箱体1.5'},{startCol:8,startRow:3,endRow:70,body:2,label:'箱体料厚改2'}],
  JP:[{startCol:1,startRow:3,endRow:55,body:null,label:'标准'}],
  JA:[{startCol:1,startRow:3,endRow:15,body:1.5,label:'标准箱体1.5'},{startCol:1,startRow:19,endRow:31,body:2,label:'箱体料厚改2'}],
  JE:[{startCol:1,startRow:3,endRow:16,body:null,label:'标准'}],
  JM:[{startCol:1,startRow:3,endRow:8,body:null,label:'标准'}],
  JK:[{startCol:1,startRow:3,endRow:8,body:null,label:'标准'}],
};

const formulaFile=await fs.promises.readFile(formulaSource);
const fixedFile=await fs.promises.readFile(fixedSource);
const formulaSha256=crypto.createHash('sha256').update(formulaFile).digest('hex');
const fixedSha256=crypto.createHash('sha256').update(fixedFile).digest('hex');
const sourceSha256=crypto.createHash('sha256').update(`FORMULA:${formulaSha256}\nFIXED:${fixedSha256}\n`).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(formulaFile);
const rules=[];
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
        const values=Array.from({length:6},(_,i)=>sheet.getCell(row,block.startCol+i).value);
        if(!text(values[1]))continue;
        rules.push({family,body_thickness_profile_mm:block.body,profile_label:block.label,
          single_door_count:door[0],double_door_count:door[1],part_name:text(values[1]),area_formula:normalizeFormula(values[2]),
          sheet_thickness_mm:number(values[3],`${family}!${row}料厚`),quantity_rule:quantityRule(values[4]),
          fixed_material_code:text(values[5])||null,source_sheet:family,source_row_no:row,source_column:block.startCol===1?'A:F':'H:M'});
      }
    }
  }
}
if(rules.length!==241)throw new Error(`材料面积规则应为 241 条，实际 ${rules.length}`);
const identity=new Set();
for(const rule of rules){
  const key=[rule.family,rule.body_thickness_profile_mm,rule.single_door_count,rule.double_door_count,rule.part_name,rule.source_row_no,rule.source_column].join('|');
  if(identity.has(key))throw new Error(`重复规则 ${key}`);identity.add(key);
}

const fixedWorkbook=new ExcelJS.Workbook();await fixedWorkbook.xlsx.load(fixedFile);
const fixedConfigs={
  操作台:{product_code:'OP_TABLE_EXP',profile_code:null},
  'JC（豪华型）':{product_code:'JC_EXP',profile_code:'LUXURY'},
  'JC（标配型）':{product_code:'JC_EXP',profile_code:'STANDARD'},
  JQ:{product_code:'JQ_EXP',profile_code:null},
  'JP超宽柜':{product_code:'JP_WIDE_EXP',profile_code:null},
  'JS超宽柜':{product_code:'JS_WIDE_EXP',profile_code:null},
};
const fixedRules=[];
for(const [sheetName,config] of Object.entries(fixedConfigs)){
  const sheet=fixedWorkbook.getWorksheet(sheetName);if(!sheet)throw new Error(`缺少经验重量工作表 ${sheetName}`);
  for(let rowNo=3;rowNo<=sheet.rowCount;rowNo++){
    const model=text(sheet.getCell(rowNo,3).value);if(!model)continue;
    fixedRules.push({product_code:config.product_code,profile_code:config.profile_code,
      material_codes:materialCodes(sheet.getCell(rowNo,8).value,`${sheetName}!H${rowNo}`),model_code:model,
      width_mm:number(sheet.getCell(rowNo,4).value,`${sheetName}!D${rowNo}`),
      height_mm:number(sheet.getCell(rowNo,5).value,`${sheetName}!E${rowNo}`),
      depth_mm:number(sheet.getCell(rowNo,6).value,`${sheetName}!F${rowNo}`),
      material_weight_kg:number(sheet.getCell(rowNo,7).value,`${sheetName}!G${rowNo}`),
      allow_dimension_scale:true,apply_waste_factor:false,source_sheet:sheetName,source_row_no:rowNo});
  }
}
if(fixedRules.length!==46)throw new Error(`经验重量规则应为 46 条，实际 ${fixedRules.length}`);
const fixedIdentity=new Set();
for(const rule of fixedRules){
  const key=[rule.product_code,rule.profile_code,rule.material_codes.join(','),rule.model_code,rule.width_mm,rule.height_mm,rule.depth_mm].join('|');
  if(fixedIdentity.has(key))throw new Error(`经验重量冲突：${key}`);fixedIdentity.add(key);
}

const version=`cabinet-material-${sourceSha256.slice(0,16)}-v2`;
const sourceFiles=[
  {kind:'AREA_FORMULA',name:path.basename(formulaSource),sha256:formulaSha256},
  {kind:'FIXED_WEIGHT',name:path.basename(fixedSource),sha256:fixedSha256},
];
const bundle={data_version:version,source_file:sourceFiles.map(file=>file.name).join('; '),source_sha256:sourceSha256,
  source_files:sourceFiles,default_waste_factor:1.2,rules,fixed_rules:fixedRules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.copyFileSync(path.join(root,'database/migrations/cabinet_material_v2.sql'),path.join(webDir,'01-create.sql'));
fs.writeFileSync(path.join(outDir,'cabinet-material-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- Combined SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_material_catalog_v2(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
const counts=Object.fromEntries(Object.keys(layouts).map(family=>[family,rules.filter(rule=>rule.family===family).length]));
const fixedCounts=Object.fromEntries([...new Set(fixedRules.map(rule=>rule.product_code))].map(code=>[code,fixedRules.filter(rule=>rule.product_code===code).length]));
const matrix=[...new Map(rules.map(rule=>{
  const key=[rule.family,rule.body_thickness_profile_mm??'通用',rule.single_door_count,rule.double_door_count].join('|');
  return [key,{family:rule.family,body:rule.body_thickness_profile_mm??'通用',door:`${rule.single_door_count}/${rule.double_door_count}`}];
})).values()].map(row=>({...row,count:rules.filter(rule=>rule.family===row.family&&(rule.body_thickness_profile_mm??'通用')===row.body&&`${rule.single_door_count}/${rule.double_door_count}`===row.door).length}));
const fixedMaterialCounts=Object.fromEntries(Object.keys(layouts).map(family=>[family,rules.filter(rule=>rule.family===family&&rule.fixed_material_code==='SECC').length]));
const report=['# 完整柜体材料重量目录生成报告','',`- 数据版本：\`${version}\``,`- 合并源 SHA-256：\`${sourceSha256}\``,'',
  ...sourceFiles.map(file=>`- ${file.kind}：\`${file.name}\`（\`${file.sha256}\`）`),'',
  `- 面积公式规则：${rules.length}`,`- 经验重量规则：${fixedRules.length}`,'',
  '## 面积公式覆盖','',...Object.entries(counts).map(([family,count])=>`- ${family}：${count} 条（固定 SECC ${fixedMaterialCounts[family]} 条）`),'',
  '| 产品 | 箱体料厚版本 | 单门/双门 | 零件行数 |','|---|---:|---:|---:|',...matrix.map(row=>`| ${row.family} | ${row.body} | ${row.door} | ${row.count} |`),'',
  '## 经验重量覆盖','',...Object.entries(fixedCounts).map(([code,count])=>`- ${code}：${count} 条`),'',
  '普通柜按面积公式、料厚、数量及密度计算净重，再乘程序输入的废料系数（默认 1.2）。经验产品按产品、JC配置、材质和尺寸匹配；标准尺寸精确命中，非标准尺寸沿用（宽+高+深）周长比例换算。经验重量不乘废料系数。','',
  '未标注材质的 JC、JP/JS 超宽柜按 SECC 导入；选择不锈钢时按数据库当前密度由 SECC 换算。JQ 与操作台已有 SUS304/SUS316 共用的明确重量，优先使用源表重量。','',
  '动态附件不使用柜体废料系数。材质固定 SECC 的普通柜零件在程序选择不锈钢时仍取 SECC 密度和报价日有效 SECC 单价。',''].join('\n');
fs.writeFileSync(path.join(outDir,'生成报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,formulaSha256,fixedSha256,area_rules:rules.length,fixed_rules:fixedRules.length,counts,fixedCounts},null,2));
