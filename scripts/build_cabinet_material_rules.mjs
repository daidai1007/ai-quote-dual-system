import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/材料重量/JS,JP,JA,JE,JK,JM材料明细-面积公式.xlsx';
const outDir=path.join(root,'database/cabinet-material/generated');
const webDir=path.join(root,'database/cabinet-material/web');
const text=value=>value==null?'':String(value).trim();
const number=(value,label)=>{const n=Number(value);if(!Number.isFinite(n)||n<=0)throw new Error(`${label}必须为正数`);return n;};
const normalizeFormula=value=>{
  let formula=text(value).replaceAll('（','(').replaceAll('）',')').replaceAll('高和宽的最小值','MIN(高度,宽度)');
  formula=formula.replaceAll('高度','__HEIGHT__').replaceAll('宽度','__WIDTH__').replaceAll('深度','__DEPTH__');
  formula=formula.replaceAll('高','高度').replaceAll('宽','宽度').replaceAll('深','深度');
  formula=formula.replaceAll('__HEIGHT__','高度').replaceAll('__WIDTH__','宽度').replaceAll('__DEPTH__','深度');
  parseFormula(formula);
  const variables=formulaVariables(formula);
  if(variables.some(v=>!['宽度','高度','深度'].includes(v))) throw new Error(`面积公式存在未知变量：${formula}`);
  return formula;
};
const quantityRule=value=>{
  if(typeof value==='number') return {kind:'CONSTANT',value:number(value,'数量')};
  const v=text(value).replaceAll(' ','');
  if(/^\d+(?:\.\d+)?$/.test(v)) return {kind:'CONSTANT',value:number(v,'数量')};
  if(v==='350≤深度≤1000，高度＜1000，数量取1，否则数量取2') return {kind:'JS_DEPTH_HEIGHT',when_true:1,when_false:2};
  if(v==='高度＞1000，数量取1，否则为0') return {kind:'HEIGHT_GT',threshold:1000,when_true:1,when_false:0};
  if(v==='宽度＞600且高度＞1000或者宽度＞800且高度＞600，数量为2，否则为0') return {kind:'JE_REINFORCEMENT',when_true:2,when_false:0};
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
const file=await fs.promises.readFile(source);
const sourceSha256=crypto.createHash('sha256').update(file).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(file);
const rules=[];
for(const [family,blocks] of Object.entries(layouts)){
  const sheet=workbook.getWorksheet(family);if(!sheet)throw new Error(`缺少工作表 ${family}`);
  for(const block of blocks){
    const starts=[];
    for(let row=block.startRow;row<=block.endRow;row++) if(text(sheet.getCell(row,block.startCol).value)==='单门/双门')starts.push(row);
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
        rules.push({
          family,body_thickness_profile_mm:block.body,profile_label:block.label,
          single_door_count:door[0],double_door_count:door[1],
          part_name:text(values[1]),area_formula:normalizeFormula(values[2]),
          sheet_thickness_mm:number(values[3],`${family}!${row}料厚`),
          quantity_rule:quantityRule(values[4]),fixed_material_code:text(values[5])||null,
          source_sheet:family,source_row_no:row,source_column:block.startCol===1?'A:F':'H:M',
        });
      }
    }
  }
}
if(rules.some(r=>r.single_door_count===null||r.double_door_count===null))throw new Error('存在未取得门型数量的材料行');
const identity=new Set();for(const r of rules){const k=[r.family,r.body_thickness_profile_mm,r.single_door_count,r.double_door_count,r.part_name,r.source_row_no,r.source_column].join('|');if(identity.has(k))throw new Error(`重复规则 ${k}`);identity.add(k);}
const version=`cabinet-material-${sourceSha256.slice(0,16)}-v1`;
const bundle={data_version:version,source_file:path.basename(source),source_sha256:sourceSha256,default_waste_factor:1.2,rules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.copyFileSync(path.join(root,'database/migrations/cabinet_material_v1.sql'),path.join(webDir,'01-create.sql'));
fs.writeFileSync(path.join(outDir,'cabinet-material-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
const stage=`-- Generated from ${bundle.source_file}\n-- SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_material_catalog_v1(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`;
fs.writeFileSync(path.join(webDir,'02-stage.sql'),stage);
const counts=Object.fromEntries(Object.keys(layouts).map(f=>[f,rules.filter(r=>r.family===f).length]));
const matrix=[...new Map(rules.map(r=>{
  const key=[r.family,r.body_thickness_profile_mm??'通用',r.single_door_count,r.double_door_count].join('|');
  return [key,{family:r.family,body:r.body_thickness_profile_mm??'通用',door:`${r.single_door_count}/${r.double_door_count}`}];
})).values()].map(row=>({...row,count:rules.filter(r=>r.family===row.family&&(r.body_thickness_profile_mm??'通用')===row.body&&`${r.single_door_count}/${r.double_door_count}`===row.door).length}));
const fixedCounts=Object.fromEntries(Object.keys(layouts).map(f=>[f,rules.filter(r=>r.family===f&&r.fixed_material_code==='SECC').length]));
const report=[`# 柜体材料规则生成报告`,``,`- 数据版本：\`${version}\``,`- 源文件 SHA-256：\`${sourceSha256}\``,`- 规则总数：${rules.length}`,'',
  ...Object.entries(counts).map(([k,v])=>`- ${k}：${v} 条（固定 SECC ${fixedCounts[k]} 条）`),'',
  '| 产品 | 箱体料厚版本 | 单门/双门 | 零件行数 |','|---|---:|---:|---:|',
  ...matrix.map(r=>`| ${r.family} | ${r.body} | ${r.door} | ${r.count} |`),'',
  `所有面积公式已通过安全算术解析；变量仅有完整变量名“宽度、高度、深度”和 MIN。数量规则已转换为结构化条件。动态附件不在此数据集中，也不使用柜体废料系数。`,
  `材质固定 SECC 的行在程序选择不锈钢时仍取 SECC 密度和 SECC 报价日有效单价。`,''].join('\n');
fs.writeFileSync(path.join(outDir,'生成报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,total:rules.length,counts},null,2));
