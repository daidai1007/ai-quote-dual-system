import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ExcelJS from '@excel.js/exceljs';
import {formulaVariables,parseFormula} from '../api/attachment_formula.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const bomSource=process.argv[2]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/辅材成本/辅材BOM清单.xlsx';
const fixedSource=process.argv[3]||'G:/gongsi/banjinxitong/板件后续二次修改/数据库最终修改/公式法报价/辅材成本/JK,JC,操作台辅材价格.xlsx';
const outDir=path.join(root,'database/cabinet-auxiliary/generated');
const webDir=path.join(root,'database/cabinet-auxiliary/web');
const text=value=>value==null?'':String(value).trim();
const number=(value,label,{zero=false}={})=>{const n=Number(value);if(!Number.isFinite(n)||(zero?n<0:n<=0))throw new Error(`${label}无效`);return n;};
const formulaOf=cell=>cell.type===ExcelJS.ValueType.Formula?text(cell.formula):'';
const scalarOf=cell=>cell.type===ExcelJS.ValueType.Formula?cell.result:cell.value;
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
const materialCodes=(value,label)=>{
  const material=text(value).toUpperCase();
  if(material==='SECC')return ['SECC'];
  if(material==='SUS304/SUS316')return ['SUS304','SUS316'];
  throw new Error(`${label} 不支持的材质：${value}`);
};

const bomFile=await fs.promises.readFile(bomSource);
const fixedFile=await fs.promises.readFile(fixedSource);
const bomSha256=crypto.createHash('sha256').update(bomFile).digest('hex');
const fixedSha256=crypto.createHash('sha256').update(fixedFile).digest('hex');
const sourceSha256=crypto.createHash('sha256').update(`BOM:${bomSha256}\nFIXED:${fixedSha256}\n`).digest('hex');
const workbook=new ExcelJS.Workbook();await workbook.xlsx.load(bomFile);
const profiles=[];const lines=[];const issues=[];
for(const sheet of workbook.worksheets){
  const isJP=sheet.name.startsWith('JP'),pieceCol=isJP?9:8,quantityCol=isJP?10:9,notesCol=isJP?11:10,priceCol=isJP?12:11,totalCol=isJP?13:12;
  const product=text(sheet.getCell(1,5).value)||(sheet.name.startsWith('JM')?'JM':'');
  if(!['JA','JE','JS','JP','JM'].includes(product))throw new Error(`${sheet.name} 产品代码无效：${product}`);
  let doorText=text(sheet.getCell(1,7).value);if(product==='JM')doorText=sheet.name.includes('双门')?'单门/双门0/1':'单门/双门1/0';
  const door=doorText.match(/单门\/双门(\d+)\/(\d+)/);if(!door)throw new Error(`${sheet.name} 门型无效：${doorText}`);
  let materialValue='';
  for(let rowNo=1;rowNo<=sheet.rowCount;rowNo++)if(text(sheet.getCell(rowNo,1).value)==='材质')materialValue=text(sheet.getCell(rowNo+1,1).value);
  const profileMaterials=materialCodes(materialValue,`${sheet.name} 材质`);
  const single=Number(door[1]),double=Number(door[2]),profileKey=`${product}:${single}/${double}:${profileMaterials.join('+')}`;
  const summary=sheet.getCell(1,3),summaryFormula=formulaOf(summary),expectedLast=Math.max(...Array.from({length:sheet.rowCount-2},(_,i)=>i+3).filter(r=>text(sheet.getCell(r,4).value)));
  const expectedRange=`${isJP?'M':'L'}3:${isJP?'M':'L'}${expectedLast}`;
  if(!summaryFormula.replaceAll('$','').toUpperCase().includes(expectedRange))issues.push(`${sheet.name}!C1 汇总范围 ${summaryFormula} 未覆盖 ${expectedRange}`);
  profiles.push({profile_key:profileKey,product_code:product,material_codes:profileMaterials,single_door_count:single,double_door_count:double,
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
      quantity_rule:resolveQuantity(sheet,rowNo,pieceCol,quantityCol),unit_price:number(scalarOf(sheet.getCell(rowNo,priceCol)),`${sheet.name}!${rowNo}单价`,{zero:true}),
      cost_kind:costKind,length_formula:lengthFormula,spray_width_m:sprayWidth,notes:text(sheet.getCell(rowNo,notesCol).value)||null,
      source_total_formula:totalFormula,source_cached_total:Number(totalCell.result??totalCell.value??0),source_sheet:sheet.name,source_row_no:rowNo});
  }
}
const profileKeys=new Set(profiles.map(p=>p.profile_key));if(profileKeys.size!==profiles.length)throw new Error('辅材门型配置重复');
if(issues.length)throw new Error(`辅材工作簿存在阻断问题：${issues.join('；')}`);

const fixedWorkbook=new ExcelJS.Workbook();await fixedWorkbook.xlsx.load(fixedFile);
const fixedConfigs={
  JK:{product_code:'JK',profile_code:null,model_column:null,width_column:2,height_column:3,depth_column:4,cost_column:5,material_column:6},
  'JC（豪华型）':{product_code:'JC_EXP',profile_code:'LUXURY'},
  'JC（标配型）':{product_code:'JC_EXP',profile_code:'STANDARD'},
  JQ:{product_code:'JQ_EXP',profile_code:null},
  'JP超宽柜':{product_code:'JP_WIDE_EXP',profile_code:null},
  'JS超宽柜':{product_code:'JS_WIDE_EXP',profile_code:null},
  操作台:{product_code:'OP_TABLE_EXP',profile_code:null},
};
const fixedRules=[];
for(const [sheetName,rawConfig] of Object.entries(fixedConfigs)){
  const sheet=fixedWorkbook.getWorksheet(sheetName);if(!sheet)throw new Error(`缺少固定辅材价格工作表 ${sheetName}`);
  const config={model_column:3,width_column:4,height_column:5,depth_column:6,cost_column:7,material_column:8,...rawConfig};
  for(let rowNo=3;rowNo<=sheet.rowCount;rowNo++){
    const width=sheet.getCell(rowNo,config.width_column).value;if(width==null||text(width)==='')continue;
    fixedRules.push({product_code:config.product_code,profile_code:config.profile_code,
      material_codes:materialCodes(sheet.getCell(rowNo,config.material_column).value,`${sheetName}!${sheet.getCell(rowNo,config.material_column).address}`),
      model_code:config.model_column?text(sheet.getCell(rowNo,config.model_column).value)||null:null,
      width_mm:number(width,`${sheetName}!${sheet.getCell(rowNo,config.width_column).address}`),
      height_mm:number(sheet.getCell(rowNo,config.height_column).value,`${sheetName}!${sheet.getCell(rowNo,config.height_column).address}`),
      depth_mm:number(sheet.getCell(rowNo,config.depth_column).value,`${sheetName}!${sheet.getCell(rowNo,config.depth_column).address}`),
      auxiliary_cost:number(sheet.getCell(rowNo,config.cost_column).value,`${sheetName}!${sheet.getCell(rowNo,config.cost_column).address}`,{zero:true}),
      allow_dimension_scale:true,source_sheet:sheetName,source_row_no:rowNo});
  }
}
if(profiles.length!==32||lines.length!==510)throw new Error(`辅材 BOM 应为 32 个材质配置/510 条明细，实际 ${profiles.length}/${lines.length}`);
if(fixedRules.length!==72)throw new Error(`固定辅材价格应为 72 条，实际 ${fixedRules.length}`);
const identities=new Set();for(const rule of fixedRules){
  const key=[rule.product_code,rule.profile_code,rule.material_codes.join(','),rule.model_code,rule.width_mm,rule.height_mm,rule.depth_mm].join('|');
  if(identities.has(key))throw new Error(`固定辅材价格冲突：${key}`);identities.add(key);
}

const version=`cabinet-auxiliary-${sourceSha256.slice(0,16)}-v3`;
const sourceFiles=[
  {kind:'BOM',name:path.basename(bomSource),sha256:bomSha256},
  {kind:'FIXED_PRICE',name:path.basename(fixedSource),sha256:fixedSha256},
];
const bundle={data_version:version,source_file:sourceFiles.map(x=>x.name).join('; '),source_sha256:sourceSha256,source_files:sourceFiles,profiles,lines,fixed_rules:fixedRules};
fs.mkdirSync(outDir,{recursive:true});fs.mkdirSync(webDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'cabinet-auxiliary-bundle.json'),JSON.stringify(bundle,null,2)+'\n');
  fs.copyFileSync(path.join(root,'database/migrations/cabinet_auxiliary_v3.sql'),path.join(webDir,'01-create.sql'));
const payloadHex=Buffer.from(JSON.stringify(bundle)).toString('hex');
fs.writeFileSync(path.join(webDir,'02-stage.sql'),`-- Generated from ${bundle.source_file}\n-- Combined SHA-256: ${sourceSha256}\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\nSELECT calc.stage_cabinet_auxiliary_catalog_v3(convert_from(decode('${payloadHex}','hex'),'UTF8')::jsonb);\nCOMMIT;\n`);
fs.writeFileSync(path.join(webDir,'03-validate.sql'),`BEGIN READ ONLY;
SELECT data_version,status,source_sha256,source_files
FROM calc.cabinet_auxiliary_catalog_version WHERE data_version='${version}';
SELECT p.product_code,count(DISTINCT p.profile_id) AS profiles,count(l.line_id) AS lines
FROM calc.cabinet_auxiliary_profile p LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
WHERE p.data_version='${version}' GROUP BY p.product_code ORDER BY p.product_code;
SELECT product_code,count(*) AS fixed_rules FROM calc.cabinet_auxiliary_fixed_rule
WHERE data_version='${version}' GROUP BY product_code ORDER BY product_code;
SELECT p.product_code,p.single_door_count,p.double_door_count,m.material_code,count(*) AS profiles
FROM calc.cabinet_auxiliary_profile p
CROSS JOIN LATERAL jsonb_array_elements_text(p.material_codes) AS m(material_code)
WHERE p.data_version='${version}'
GROUP BY p.product_code,p.single_door_count,p.double_door_count,m.material_code HAVING count(*)<>1;
SELECT count(*) AS unsupported_quantity_rules FROM calc.cabinet_auxiliary_line l
JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
WHERE p.data_version='${version}' AND l.quantity_rule->>'kind' NOT IN ('CONSTANT','HEIGHT_GT');
COMMIT;
`);
fs.writeFileSync(path.join(webDir,'04-activate.sql'),`BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_auxiliary_catalog_v3('${version}');
COMMIT;
`);
fs.writeFileSync(path.join(webDir,'05-verify.sql'),`BEGIN READ ONLY;
SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,
       count(DISTINCT l.line_id) AS lines,count(DISTINCT r.rule_id) AS fixed_rules
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
LEFT JOIN calc.cabinet_auxiliary_fixed_rule r ON r.data_version=v.data_version
GROUP BY v.data_version,v.status ORDER BY v.created_at;
SELECT count(*) FILTER(WHERE status='ACTIVE') AS active_versions FROM calc.cabinet_auxiliary_catalog_version;
SELECT p.product_code,p.single_door_count,p.double_door_count,m.material_code,count(*) AS profiles
FROM calc.cabinet_auxiliary_profile p
JOIN calc.cabinet_auxiliary_catalog_version v USING(data_version)
CROSS JOIN LATERAL jsonb_array_elements_text(p.material_codes) AS m(material_code)
WHERE v.status='ACTIVE'
GROUP BY p.product_code,p.single_door_count,p.double_door_count,m.material_code HAVING count(*)<>1;
SELECT calc.get_auxiliary_cost('JK','DEFAULT','','SECC',300,200,80) AS jk_secc,
       calc.get_auxiliary_cost('JQ_EXP','DEFAULT','JQ609648','SUS316',600,960,480) AS jq_sus316,
       calc.get_auxiliary_cost('JC_EXP','DEFAULT','JC601660-1','SECC',600,1600,600) AS jc_luxury;
COMMIT;
`);
fs.writeFileSync(path.join(webDir,'06-rollback.sql'),`BEGIN;
SET LOCAL lock_timeout='5s';
DO $$
DECLARE v_previous text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_auxiliary_catalog_version'));
  SELECT data_version INTO v_previous FROM calc.cabinet_auxiliary_catalog_version
  WHERE status='RETIRED' AND data_version<>'${version}' ORDER BY created_at DESC LIMIT 1;
  IF v_previous IS NULL THEN RAISE EXCEPTION 'No previous RETIRED auxiliary version is available'; END IF;
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='RETIRED',activated_at=NULL WHERE data_version='${version}' AND status='ACTIVE';
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=v_previous;
END $$;
COMMIT;
`);
fs.writeFileSync(path.join(webDir,'07-delete-retired.sql'),`BEGIN;
SET LOCAL lock_timeout='5s';
DELETE FROM calc.cabinet_auxiliary_catalog_version WHERE status='RETIRED';
COMMIT;
`);
const bomCounts=Object.fromEntries([...new Set(profiles.map(p=>p.product_code))].map(p=>[p,lines.filter(l=>l.profile_key.startsWith(`${p}:`)).length]));
const fixedCounts=Object.fromEntries([...new Set(fixedRules.map(r=>r.product_code))].map(p=>[p,fixedRules.filter(r=>r.product_code===p).length]));
const report=['# 完整柜体辅材目录读取报告','',`- 数据版本：\`${version}\``,`- 合并源 SHA-256：\`${sourceSha256}\``,'',
  ...sourceFiles.map(x=>`- ${x.kind}：\`${x.name}\`（\`${x.sha256}\`）`),'',
  `- BOM 材质门型配置：${profiles.length}` ,`- BOM 明细：${lines.length}`,`- 固定/尺寸价格：${fixedRules.length}`,'',
  '## BOM 覆盖','',...Object.entries(bomCounts).map(([k,v])=>`- ${k}：${v} 条明细`),'',
  '## 固定价格覆盖','',...Object.entries(fixedCounts).map(([k,v])=>`- ${k}：${v} 条价格`),'',
  '宽度、高度、深度统一取当前程序报价行输入的柜体尺寸（mm）。BOM 的 A3/A5/A7 仅是公式占位，不使用缓存尺寸。动态长度小于 0 时按源 IF 公式取 0。JP 辅材框架喷塑面积按长度×0.198×内部数量，喷塑金额使用报价日当前喷塑单价；不喷塑为 0。','',
  'JK、JC、JQ、JP/JS 超宽柜和操作台按产品、配置及材质选择固定价格；标准尺寸精确命中，非标准尺寸沿用现有规则，选择周长最接近的记录并按（宽+高+深）比例换算。普通柜按门数组合计算 BOM。辅材成本和明细只替换公式法报价，快速报价不变。','',
  '- 两份工作簿没有发现同级重复规则。','- JC 和 JP/JS 超宽柜源表仅提供 SECC；选择 SUS304/SUS316 时返回明确的缺规则错误，不再读取旧数据。',''].join('\n');
fs.writeFileSync(path.join(outDir,'读取报告.md'),report);
console.log(JSON.stringify({version,sourceSha256,profiles:profiles.length,lines:lines.length,fixed_rules:fixedRules.length,bomCounts,fixedCounts,issues},null,2));
