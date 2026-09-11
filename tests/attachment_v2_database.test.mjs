// Integration target is deliberately fixed to a disposable loopback test cluster.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync, spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {createAttachmentService} from '../api/attachment_service.mjs';
import ExcelJS from '@excel.js/exceljs';
import {requiredParameters} from '../api/attachment_cost.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const psql=process.env.ATTACHMENT_TEST_PSQL || 'G:/PostgreSQL/18/bin/psql.exe';
const db=`attachment_v2_test_${Date.now()}`;
const base=['-X','-w','-h','127.0.0.1','-p','55439','-U','attachment_test','-v','ON_ERROR_STOP=1','-A','-t','-q'];
function sql(text,database=db) { return execFileSync(psql,[...base,'-d',database],{input:text,encoding:'utf8',stdio:['pipe','pipe','pipe']}).trim(); }
function file(relative,database=db) { return sql(fs.readFileSync(path.join(root,relative),'utf8'),database); }
const json=value=>`convert_from(decode('${Buffer.from(JSON.stringify(value)).toString('hex')}','hex'),'UTF8')::jsonb`;
const original=JSON.parse(fs.readFileSync(path.join(root,'database/attachment-v2/generated/attachment-bundle.json')));
let bundle;

test('实际HTTP API与本地PostgreSQL：V2持久化、基础计算回滚及旧客户端门槛',async()=>{
  const target=`${db}_http`;
  sql(`CREATE DATABASE ${target};`,'postgres');
  for(const f of ['tests/fixtures/attachment_online_schema_20260911.sql','database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql','tests/fixtures/attachment_api_base_stub.sql']) file(f,target);
  const reserve=net.createServer();await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
  const child=spawn(process.execPath,[path.join(root,'api/server.mjs')],{cwd:root,windowsHide:true,env:{...process.env,
    DATABASE_URL:'',PGSERVICE:undefined,PGSERVICEFILE:undefined,PGPASSWORD:'',RENDER:'',AI_QUOTE_API_KEY:'',AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),PSQL_PATH:psql,
    AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:'55439',AI_QUOTE_DB_USER:'attachment_test',AI_QUOTE_DB_NAME:target,
    AI_QUOTE_ATTACHMENT_V2_VERSION:original.data_version,AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED:'1'}});
  try {
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('local API startup timeout')),10000);
      child.stdout.on('data',data=>{if(String(data).includes('listening')){clearTimeout(timer);resolve();}});
      child.once('error',reject);child.once('exit',code=>{clearTimeout(timer);reject(new Error(`API exited ${code}`));});});
    const call=async(route,body)=>{const response=await fetch(`http://127.0.0.1:${port}${route}`,body?{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}:{});return {status:response.status,body:await response.json()};};
    const catalog=await call('/api/attachments/catalog?v=2');assert.equal(catalog.status,200,JSON.stringify(catalog));
    const price=catalog.body.items.find(a=>a.source_row_no===208).attachment_price_id;
    const input={quote_id:'HTTP_LOCAL',attachment_contract:2,product_code:'JP',material_code:'SECC',width_mm:800,height_mm:2000,depth_mm:600,quote_date:'2026-09-11',coating_type:'橘纹',attachments:[{attachment_price_id:price,quantity:2,formula_amount:0,unit_price_override:0}]};
    const response=await call('/api/quotes/calculate-dual',input);
    assert.equal(response.status,200,JSON.stringify(response));
    assert.equal(response.body.formula_cost.total_cost,112);assert.equal(response.body.quick_quote.total_cost,240);
    assert.ok(response.body.attachments[0].attachment_selection_id);
    assert.equal(sql('SELECT count(*) FROM calc.local_base_probe;',target),'0','base calculation must roll back its transient writes');
    assert.equal(sql("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='HTTP_LOCAL';",target),'1');
    const document={quote_id:'HTTP_DOCUMENT',company_code:'LOCAL',company_name:'本地测试',quote_date:input.quote_date,items:[{...input,
      quote_line_id:response.body.quote_line_id,attachments:response.body.attachments,quantity:1,formula:{total_cost:0},quick:{total_cost:0}}]};
    const checked=await call('/api/quotes/confirm-check',document);assert.equal(checked.status,200,JSON.stringify(checked));
    assert.equal(sql('SELECT count(*) FROM calc.quote_document;',target),'0');
    const confirmed=await call('/api/quotes/confirm',document);assert.equal(confirmed.status,200,JSON.stringify(confirmed));
    const historic=await call('/api/company-history/match',{...input,company_code:'LOCAL'});
    assert.equal(historic.body.payload.formula.total_cost,112);
    assert.equal(historic.body.payload.quick.total_cost,240);
    assert.equal(historic.body.payload.attachments[0].attachment_selection_id,response.body.attachments[0].attachment_selection_id);
    const invalid=await call('/api/attachments/preview',{...input,attachments:[{attachment_price_id:99999,quantity:1}]});
    assert.equal(invalid.status,400);assert.match(invalid.body.message,/不属于当前目录/);
    const gangedCabinets=[
      {width_mm:400,height_mm:2000,depth_mm:600,single_door_count:1,double_door_count:0},
      {width_mm:600,height_mm:2000,depth_mm:600,single_door_count:0,double_door_count:1},
    ];
    const gangedInput={...input,quote_id:'HTTP_GANGED',ganged_cabinet_count:2,ganged_cabinets:gangedCabinets,
      ganged_cabinet_inputs:gangedCabinets.map((row,index)=>({...input,...row,quote_id:`HTTP_GANGED-${index+1}`,
        product_code:index?'JP_DOUBLE':'JP_SINGLE',attachments:[]})),
      attachments:[{attachment_price_id:price,quantity:2,ganged_cabinet_index:1}]};
    const gangedPreview=await call('/api/attachments/preview',gangedInput);
    assert.equal(gangedPreview.status,200,JSON.stringify(gangedPreview));
    assert.equal(gangedPreview.body.attachments[0].ganged_cabinet_index,1);
    assert.equal(gangedPreview.body.attachments[0].environment.width_mm,600);
    const ganged=await call('/api/attachments/snapshot-ganged',{...gangedInput,base_result:{
      quote_id:'HTTP_GANGED-1',formula_cost:{total_cost:200,attachment_fee:0,labor_cost:20,management_fee:2.6},
      quick_quote:{base_price:400,total_cost:400,attachment_fee:0},risk_flags:[],ganged_cabinet_results:[],
    }});
    assert.equal(ganged.status,200,JSON.stringify(ganged));
    assert.equal(ganged.body.formula_cost.total_cost,212);assert.equal(ganged.body.quick_quote.total_cost,440);
    assert.equal(ganged.body.attachments[0].ganged_cabinet_index,1);assert.ok(ganged.body.quote_line_id);
    assert.equal(sql("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='HTTP_GANGED';",target),'1');
    const gangedDocument={quote_id:'HTTP_GANGED_DOCUMENT',company_code:'LOCAL',company_name:'本地并柜测试',quote_date:input.quote_date,
      items:[{...gangedInput,quote_line_id:ganged.body.quote_line_id,attachments:ganged.body.attachments,quantity:1,
        formula:ganged.body.formula_cost,quick:ganged.body.quick_quote}]};
    const gangedChecked=await call('/api/quotes/confirm-check',gangedDocument);
    assert.equal(gangedChecked.status,200,JSON.stringify(gangedChecked));
    const changedGanged=structuredClone(gangedDocument);changedGanged.items[0].ganged_cabinets[1].width_mm=601;
    const changedChecked=await call('/api/quotes/confirm-check',changedGanged);
    assert.equal(changedChecked.status,400);assert.match(changedChecked.body.message,/并柜明细已变化/);
    sql(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${original.data_version}'); COMMIT;`,target);
    assert.equal((await call('/api/attachments/catalog')).status,426);
    assert.equal((await call('/api/quotes/calculate-dual',{...input,attachment_contract:undefined,attachments:[{item_name:'门限位器',quantity:1}]})).status,426);
  } finally {child.kill();await new Promise(resolve=>child.exitCode!==null?resolve():child.once('exit',resolve));}
});

test('V2服务读取STAGED预览、按ID双金额、人工错误阻断和历史快照复用',async()=>{
  const target=`${db}_service`;
  sql(`CREATE DATABASE ${target};`,'postgres');
  for(const f of ['tests/fixtures/attachment_online_schema_20260911.sql','database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql']) file(f,target);
  sql(`CREATE TABLE calc.material(material_code varchar PRIMARY KEY,density_g_cm3 numeric);
    INSERT INTO calc.material VALUES('SECC',7.85),('SUS304',7.93),('SUS316',7.98);
    CREATE FUNCTION calc.get_material_unit_price(varchar,date) RETURNS numeric LANGUAGE sql AS 'SELECT CASE WHEN $1=''SECC'' THEN 5 ELSE 20 END::numeric';
    CREATE FUNCTION calc.get_spray_unit_price(date,varchar) RETURNS numeric LANGUAGE sql AS 'SELECT 10::numeric';`,target);
  const service=createAttachmentService({runPsql:async text=>sql(text,target),env:{AI_QUOTE_ATTACHMENT_V2_VERSION:original.data_version,AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED:'1'},calculateBase:async input=>{
    assert.deepEqual(input.attachments,[]);
    return {formula_cost:{total_cost:100,material_cost:78.7,auxiliary_cost:5,spray_cost:5,labor_cost:10,management_fee:1.3,product_area_m2:2,attachment_fee:0},quick_quote:{base_price:200,total_cost:200,attachment_fee:0}};
  }});
  const catalog=await service.catalog();assert.equal(catalog.items.length,226);
  assert.equal(await service.hasActive(),false);
  const price=Number(catalog.items.find(q=>q.source_row_no===208).attachment_price_id);
  const input={quote_id:'SERVICE',product_code:'JP',material_code:'SECC',width_mm:800,height_mm:2000,depth_mm:600,coating_type:'橘纹',quote_date:'2026-09-11',attachments:[{attachment_price_id:price,quantity:2,unit_price_override:0,formula_amount:0}]};
  const result=await service.calculate(input);
  assert.equal(result.formula_cost.total_cost,112);assert.equal(result.quick_quote.total_cost,240);
  assert.ok(result.attachments[0].attachment_selection_id);
  const gangedRows=[
    {width_mm:400,height_mm:2000,depth_mm:600,single_door_count:1,double_door_count:0},
    {width_mm:600,height_mm:2000,depth_mm:600,single_door_count:0,double_door_count:1},
  ];
  const ganged=await service.snapshotGanged({...input,quote_id:'SERVICE_GANGED',ganged_cabinet_count:2,
    ganged_cabinets:gangedRows,ganged_cabinet_inputs:gangedRows.map((row,index)=>({...input,...row,
      product_code:index?'JP_DOUBLE':'JP_SINGLE',attachments:[]})),
    attachments:[{attachment_price_id:price,quantity:2,ganged_cabinet_index:1}],base_result:{
      quote_id:'SERVICE_GANGED-1',formula_cost:{total_cost:200,attachment_fee:0,labor_cost:20,management_fee:2.6},
      quick_quote:{base_price:400,total_cost:400,attachment_fee:0},risk_flags:[],ganged_cabinet_results:[],
    }});
  assert.equal(ganged.formula_cost.total_cost,212);assert.equal(ganged.quick_quote.total_cost,440);
  assert.equal(ganged.attachments[0].ganged_cabinet_index,1);
  assert.equal(ganged.attachments[0].product_code,'JP_DOUBLE');assert.equal(ganged.attachments[0].environment.width_mm,600);
  const gangedDocument={items:[{...input,quote_id:'SERVICE_GANGED',ganged_cabinet_count:2,ganged_cabinets:gangedRows,
    attachments:ganged.attachments,quote_line_id:ganged.quote_line_id,attachment_contract:2,
    formula:ganged.formula_cost,quick:ganged.quick_quote}]};
  assert.equal((await service.hydrateDocument(gangedDocument)).items[0].formula.total_cost,212);
  const changedGanged=structuredClone(gangedDocument);changedGanged.items[0].ganged_cabinets[0].width_mm=401;
  await assert.rejects(()=>service.hydrateDocument(changedGanged),/并柜明细已变化/);
  const again=await service.calculate(input);assert.notEqual(again.quote_line_id,result.quote_line_id);
  const document={items:[{...input,attachments:result.attachments,quote_line_id:result.quote_line_id,attachment_contract:2,formula:result.formula_cost,quick:result.quick_quote}]};
  await service.hydrateDocument(document);
  const manipulated=structuredClone(document);manipulated.items[0].formula.total_cost=0;manipulated.items[0].quick.total_cost=0;
  assert.equal((await service.hydrateDocument(manipulated)).items[0].formula.total_cost,112);
  manipulated.items[0].labor_multiplier=2;
  assert.equal((await service.hydrateDocument(manipulated)).items[0].formula.total_cost,123.3);
  const stripped=structuredClone(document);delete stripped.items[0].attachment_contract;
  stripped.items[0].attachments=[{attachment_price_id:price,quantity:2}];
  await assert.rejects(()=>service.hydrateDocument(stripped),/报价行ID/);
  const dateChanged=structuredClone(document);dateChanged.items[0].quote_date='2026-09-12';
  await assert.rejects(()=>service.hydrateDocument(dateChanged),/quote_date/);
  const tampered=structuredClone(document);tampered.items[0].attachments[0].quantity=3;
  await assert.rejects(()=>service.hydrateDocument(tampered),/重新计算/);
  const dynamic=catalog.items.find(q=>q.rules.some(r=>JSON.stringify(r.formulas).includes('底座高度')));
  assert.ok(dynamic);
  const missing=await service.preview({...input,attachments:[{attachment_price_id:dynamic.attachment_price_id,quantity:1}]});
  assert.equal(missing.attachments[0].status,'ERROR');assert.equal(missing.formula_attachment_fee,null);
  assert.match(missing.attachments[0].error,/底座高度/);
  const separate=await service.calculate({...input,attachments:[100,200].map(height=>({attachment_price_id:dynamic.attachment_price_id,quantity:1,manual_inputs:{底座高度:height}}))});
  assert.notEqual(separate.attachments[0].attachment_selection_id,separate.attachments[1].attachment_selection_id);
  assert.notEqual(separate.attachments[0].formula_amount,separate.attachments[1].formula_amount);
  assert.deepEqual(separate.attachments.map(a=>a.manual_inputs.底座高度),[100,200]);
  // Exercise every actual dynamic source rule through the installed numeric
  // snapshot guard, including monetary half-step boundaries exposed above.
  const dynamicRules=[...new Map(catalog.items.flatMap(a=>a.rules).filter(r=>r.method==='CALCULATED').map(r=>[r.rule_id,r])).values()];
  assert.equal(dynamicRules.length,30);
  for(const rule of dynamicRules){
    const item=catalog.items.find(a=>a.rules.some(r=>r.rule_id===rule.rule_id));
    const manual=Object.fromEntries(requiredParameters(rule).filter(p=>p.source==='MANUAL').map(p=>[p.name,100]));
    const saved=await service.calculate({...input,product_code:rule.products[0]||'JK',material_code:rule.materials[0]||'SECC',attachments:[{attachment_price_id:item.attachment_price_id,quantity:2,manual_inputs:manual}]});
    assert.equal(saved.attachments[0].status,'CALCULATED',`source row ${rule.source_row_no}: ${JSON.stringify(saved.attachments[0])}`);
  }
  const bad=await service.calculate({...input,attachments:[{attachment_price_id:dynamic.attachment_price_id,quantity:1}]});
  assert.equal(bad.formula_cost.total_cost,null);
  await assert.rejects(()=>service.hydrateDocument({items:[{...input,attachments:bad.attachments,attachment_contract:2,quote_line_id:bad.quote_line_id}]}),/存在错误/);
  const select=(source_row_no,quantity=1,manual_inputs={})=>({attachment_price_id:catalog.items.find(q=>q.source_row_no===source_row_no).attachment_price_id,quantity,manual_inputs});
  const dynamicInputs={底座高度:100,通风顶罩高度:150,分段板高度:200};
  const dynamicRow=catalog.items.find(q=>q.rules.some(r=>r.method==='CALCULATED'&&r.auxiliary_list));
  const complete=await service.calculate({...input,attachments:[select(208,2),select(98,3),{attachment_price_id:dynamicRow.attachment_price_id,quantity:2,manual_inputs:dynamicInputs}]});
  assert.ok(complete.attachments.every(a=>a.status!=='ERROR'),JSON.stringify(complete.attachments));
  const stainless=await service.calculate({...input,material_code:'SUS304',attachments:[select(208,2)]});
  assert.equal(stainless.attachments[0].formula_unit_cost,17.5);assert.equal(stainless.attachments[0].quick_amount,40);
  const multi={quote_id:'LOCAL-V2-SAMPLE',quote_date:input.quote_date,company_name:'本地兼容验证样例',items:[complete,stainless].map((r,i)=>({...input,material_code:i?'SUS304':'SECC',name:'同型号测试产品',model_code:'',quantity:1,formula_discount:1,quick_discount:1,labor_multiplier:1,attachments:r.attachments,attachment_contract:2,quote_line_id:r.quote_line_id,formula:r.formula_cost,quick:r.quick_quote}))};
  const hydrated=await service.hydrateDocument(multi);
  const outputDir=path.join(root,'test-output/attachment-cost-v2');
  const manualComplete=await service.preview({...input,attachments:[{attachment_price_id:dynamic.attachment_price_id,quantity:1,manual_inputs:dynamicInputs}]});
  assert.equal(manualComplete.attachments[0].status,'CALCULATED');
  fs.writeFileSync(path.join(outputDir,'api-client-fixtures.json'),JSON.stringify({catalog,input,result,missing,manualComplete,complete,stainless,document:hydrated},null,2));
  fs.writeFileSync(path.join(outputDir,'api-snapshot-export.json'),JSON.stringify(hydrated,null,2));
  execFileSync(process.execPath,[path.join(root,'export_dual_quote_workbook.mjs'),path.join(outputDir,'api-snapshot-export.json'),path.join(outputDir,'api-snapshot-export.xlsx')],{cwd:root,windowsHide:true});
  const workbook=new ExcelJS.Workbook();await workbook.xlsx.readFile(path.join(outputDir,'api-snapshot-export.xlsx'));
  const sheet=workbook.getWorksheet('附件双报价明细');assert.equal(sheet.rowCount,5);
  assert.equal(sheet.getCell(2,1).value,complete.quote_line_id);assert.equal(sheet.getCell(5,1).value,stainless.quote_line_id);
  assert.equal(sheet.getCell(4,20).value,complete.attachments[2].auxiliary_list);
  assert.equal(sheet.getCell(3,25).value,'仅快速报价');assert.equal(sheet.getCell(3,23).value,null);
  sql(`UPDATE calc.attachment_cost_rule SET fixed_cost=999 WHERE data_version='${original.data_version}' AND source_row_no=51;`,target);
  const historic=await service.hydrateDocument(document);
  assert.equal(historic.items[0].attachments[0].formula_unit_cost,6);
  const unconfigured=createAttachmentService({runPsql:async text=>sql(text,target),env:{},calculateBase:()=>{}});
  await assert.rejects(()=>unconfigured.catalog(),/没有可用/);
});

test('用户提供的线上结构：精度、真实约束、旧函数保留和同源多版本共存',()=>{
  const target=`${db}_online`;
  sql(`CREATE DATABASE ${target};`,'postgres');
  file('tests/fixtures/attachment_online_schema_20260911.sql',target);
  const legacyDefinitions=()=>sql(`SELECT jsonb_build_object(
    'functions',(SELECT jsonb_agg(pg_get_functiondef(p.oid) ORDER BY p.oid::regprocedure::text) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='calc' AND p.proname IN ('get_attachment_fee','get_attachment_price','add_attachment_selection')),
    'views',(SELECT jsonb_agg(to_jsonb(v) ORDER BY viewname) FROM pg_views v WHERE schemaname='calc' AND viewname IN ('v_attachment_selection_cost','v_attachment_price','v_attachment_price_classified')));`,target);
  const before=legacyDefinitions();
  const q=original.catalog[0];
  // A synthetic existing row uses exactly the incoming Excel source coordinates.
  sql(`INSERT INTO calc.attachment_price(attachment_category,item_name,price,source_file,source_sheet,source_row_no,price_source)
    SELECT '旧分类','同源旧附件',77.7777,q->>'source_file',q->>'source_sheet',(q->>'source_row_no')::integer,'Excel' FROM (SELECT ${json(q)} AS q) t;
    INSERT INTO calc.attachment_selection(quote_id,product_code,attachment_price_id,item_name,quantity)
    SELECT 'LEGACY_NULL','JP',attachment_price_id,item_name,2 FROM calc.attachment_price WHERE item_name='同源旧附件';`,target);
  assert.equal(sql("SELECT calc.get_attachment_fee('LEGACY_NULL','JP');",target),'155.56');
  file('database/attachment-v2/web/01-prepare.sql',target);
  file('database/attachment-v2/web/01-prepare.sql',target);
  assert.equal(sql("SELECT count(*) FROM pg_constraint WHERE conrelid='calc.attachment_price'::regclass AND conname='uq_attachment_price_source';",target),'0');
  assert.equal(sql("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='calc.attachment_price'::regclass AND conname='uq_attachment_price_source_version';",target),'UNIQUE NULLS NOT DISTINCT (source_file, source_sheet, source_row_no, price_source, data_version)');
  file('database/attachment-v2/web/02-stage.sql',target);
  file('database/attachment-v2/web/03-verify.sql',target);
  assert.equal(sql(`SELECT price,quick_face_price FROM calc.attachment_price WHERE data_version='${original.data_version}' AND import_key='${q.import_key}';`,target),'524.5939|524.593927');
  assert.equal(sql(`SELECT count(*) FROM calc.attachment_classification WHERE classification_source='${original.data_version}';`,target),'226');
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;',target),'2');
  // Legacy NULL-version duplicates and within-version duplicates remain prohibited.
  for(const version of ['NULL',`'${original.data_version}'`]) assert.throws(()=>sql(`INSERT INTO calc.attachment_price(attachment_category,item_name,source_file,source_sheet,source_row_no,price_source,data_version)
    SELECT attachment_category,item_name,source_file,source_sheet,source_row_no,price_source,data_version FROM calc.attachment_price
    WHERE data_version IS NOT DISTINCT FROM ${version} LIMIT 1;`,target));
  const next=structuredClone(original);next.data_version='test-online-next';
  for(const row of [...next.catalog,...next.rules]) row.data_version=next.data_version;
  sql(`SELECT calc.stage_attachment_catalog_v2(${json(next)});`,target);
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price;',target),'454');
  assert.equal(sql("SELECT count(*) FROM calc.attachment_selection;",target),'2');
  assert.equal(sql("SELECT calc.get_attachment_fee('LEGACY_NULL','JP');",target),'155.56');
  assert.equal(sql("SELECT calc.get_attachment_fee('HISTORY','JP');",target),'12.34');
  assert.equal(legacyDefinitions(),before);
});

test('先停用再导入同事务：门槛、失败恢复旧目录、成功保留历史及重复执行阻断',()=>{
  const target=`${db}_replace`;
  sql(`CREATE DATABASE ${target};`,'postgres');
  for(const f of ['tests/attachment_v2_fixture.sql','database/migrations/attachment_cost_v2.sql','database/attachment-v2/02-import-functions.sql','database/attachment-v2/02b-snapshot-guards.sql']) file(f,target);
  const replacement=fs.readFileSync(path.join(root,'database/attachment-v2/generated/03-replace-active-catalog.sql'),'utf8');
  assert.throws(()=>sql(replacement,target));
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;',target),'1');
  const withError=replacement.replace('SELECT calc.activate_attachment_catalog_v2(payload)',`UPDATE attachment_import_stage SET payload=jsonb_set(payload,'{report,issues}','["TEST_ONLY forced import failure"]'::jsonb);\nSELECT calc.activate_attachment_catalog_v2(payload)`);
  const ready="SET calc.attachment_v2_api_ready='on';\n";
  assert.throws(()=>sql(ready+withError,target));
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;',target),'1');
  assert.equal(sql('SELECT count(*) FROM calc.attachment_catalog_version;',target),'0');
  sql(ready+replacement,target);
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;',target),'226');
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price;',target),'227');
  assert.equal(sql('SELECT count(*) FROM calc.attachment_classification;',target),'227');
  assert.equal(sql("SELECT unit_price FROM calc.attachment_selection WHERE quote_id='HISTORY';",target),'12.3400');
  assert.throws(()=>sql(ready+replacement,target));
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;',target),'226');
});
test('数据库隔离和增量迁移保留legacy记录、视图',()=>{
  const exists=sql(`SELECT count(*) FROM pg_database WHERE datname='${db}';`,'postgres');
  assert.equal(exists,'0','Use a fresh isolated test database, never reset an existing database.');
  sql(`CREATE DATABASE ${db};`,'postgres');
  file('tests/attachment_v2_fixture.sql');
  file('database/attachment-v2/01-readonly-preflight.sql');
  const webReport=JSON.parse(file('database/attachment-v2/01b-web-structure-details.sql'));
  assert.equal(webReport.database,db);
  assert.equal(new Set(webReport.columns.map(c=>c.table_name)).size,3);
  file('database/migrations/attachment_cost_v2.sql');
  file('database/attachment-v2/02-import-functions.sql');
  file('database/attachment-v2/02b-snapshot-guards.sql');
  file('database/migrations/attachment_cost_v2.sql'); // expansion rerun is safe
  assert.equal(sql("SELECT unit_price FROM calc.attachment_selection WHERE quote_id='HISTORY';"),'12.3400');
  assert.equal(sql("SELECT count(*) FROM calc.v_attachment_selection_cost;"),'1');
});
test('注入未确认问题会阻止导入，完整源未通过兼容门槛也全部回滚',()=>{
  const blocked=structuredClone(original);
  blocked.report.issues.push({message:'TEST_ONLY未确认规则'});
  assert.throws(()=>sql(`BEGIN; SELECT calc.stage_attachment_catalog_v2(${json(blocked)}); COMMIT;`),/Command failed/);
  assert.throws(()=>sql(`BEGIN; SELECT calc.activate_attachment_catalog_v2(${json(original)}); COMMIT;`),/Command failed/);
  assert.equal(sql('SELECT count(*) FROM calc.attachment_catalog_version;'),'0');
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price;'),'1');
});
test('合成干净数据stage不改变活动目录，切换必须单独通过兼容门槛',()=>{
  // A small explicitly synthetic test bundle, never the production import artifact.
  const q=original.catalog[0]; const r=original.rules.find(r=>r.source_row_no===2);
  bundle={data_version:'test-fixture-v1',source_sha256:'a'.repeat(64),report:{issues:[],unmapped_rules:[],counts:{quick:2,rules:1,bindings:1}},
    catalog:[{...q,data_version:'test-fixture-v1',import_key:'Q1'},{...q,data_version:'test-fixture-v1',import_key:'Q2',source_row_no:9999,item_name:'快速独有'}],
    rules:[{...r,data_version:'test-fixture-v1',import_key:'R1',method:'FIXED',fixed_cost:27.56,products:[],formulas:{},parameters:[],auxiliary_list:'原文第一行\n原文第二行',issues:[]}],
    bindings:[{attachment_key:'Q1',rule_key:'R1'}]};
  sql(`SELECT calc.stage_attachment_catalog_v2(${json(bundle)});`);
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;'),'1');
  assert.equal(sql("SELECT quick_face_price FROM calc.attachment_price WHERE import_key='Q1';"),'524.593927');
  assert.equal(sql("SELECT price FROM calc.attachment_price WHERE import_key='Q1';"),'524.59');
  assert.throws(()=>sql("SELECT calc.switch_attachment_catalog_v2('test-fixture-v1');"));
  sql("BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('test-fixture-v1'); COMMIT;");
  assert.equal(sql('SELECT count(*) FROM calc.attachment_price WHERE is_active;'),'2');
  assert.equal(sql("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='HISTORY';"),'1');
});
let priceId,ruleId;
const owner='11111111-1111-4111-8111-111111111111';
const environment={product_code:'JP',width_mm:800,height_mm:2000,depth_mm:600,material_code:'SECC',density_g_cm3:7.85,material_unit_price:5,spray_unit_price:10,coating_type:'橘纹',quote_date:'2026-09-10'};
function insert(status='FIXED',overrides={}) {
  const row={quote_line_id:owner,quote_id:'NEW',product_code:'JP',attachment_price_id:priceId,quantity:2,unit_price:524.5939,price_sign:1,
    calculation_status:status,cost_rule_id:ruleId,rule_version:'test-fixture-v1',catalog_version:'test-fixture-v1',manual_inputs:{底座高度:100},environment_snapshot:environment,quick_face_price:524.593927,quick_amount:1049.19,
    formula_unit_cost:27.56,formula_amount:55.12,cost_snapshot:{item_name:'JP控制柜侧板',category_level1:'侧板',category_level2:'',unit:'副',auxiliary_list:'原文第一行\n原文第二行'},...overrides};
  return sql(`INSERT INTO calc.attachment_selection(${Object.keys(row).join(',')}) SELECT ${Object.entries(row).map(([key,value])=>typeof value==='object'&&value!==null?`${json(value)}`:value===null?'NULL':typeof value==='string'?`'${value.replaceAll("'","''")}'`:value).join(',')} RETURNING attachment_selection_id;`);
}
test('快照固定成本、辅材原文、不可变性及错误汇总',()=>{
  priceId=Number(sql("SELECT attachment_price_id FROM calc.attachment_price WHERE import_key='Q1';"));
  ruleId=Number(sql("SELECT rule_id FROM calc.attachment_cost_rule WHERE import_key='R1';"));
  sql(`INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot) VALUES('${owner}','NEW','JP',${json(environment)});`);
  const id=insert();
  assert.equal(sql(`SELECT formula_fee FROM calc.get_attachment_dual_fee('${owner}');`),'55.12');
  assert.equal(JSON.parse(sql(`SELECT to_json(cost_snapshot->>'auxiliary_list') FROM calc.attachment_selection WHERE attachment_selection_id=${id};`)),'原文第一行\n原文第二行');
  assert.throws(()=>sql(`UPDATE calc.attachment_selection SET quantity=3 WHERE attachment_selection_id=${id};`));
  assert.throws(()=>sql(`DELETE FROM calc.attachment_selection WHERE attachment_selection_id=${id};`));
  assert.throws(()=>sql(`UPDATE calc.attachment_quote_line SET product_code='JE' WHERE quote_line_id='${owner}';`));
  assert.throws(()=>insert('FIXED',{quick_face_price:1,quick_amount:2}));
  assert.throws(()=>insert('FIXED',{formula_unit_cost:1,formula_amount:2}));
  assert.throws(()=>insert('FIXED',{quote_id:'WRONG'}));
  assert.throws(()=>insert(null));
  insert('ERROR',{formula_unit_cost:null,formula_amount:null,error_message:'缺少人工参数'});
  assert.equal(sql(`SELECT formula_fee IS NULL,error_count FROM calc.get_attachment_dual_fee('${owner}');`),'t|1');
  assert.throws(()=>sql(`SELECT calc.get_attachment_formula_fee_strict('${owner}');`));
});
test('同型号多行隔离和仅快速报价NULL不制造错误',()=>{
  const other='22222222-2222-4222-8222-222222222222';
  sql(`INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot) VALUES('${other}','NEW','JP',${json(environment)});`);
  const quickId=Number(sql("SELECT attachment_price_id FROM calc.attachment_price WHERE import_key='Q2';"));
  insert('QUICK_ONLY',{quote_line_id:other,attachment_price_id:quickId,cost_rule_id:null,rule_version:null,formula_unit_cost:null,formula_amount:null,cost_snapshot:{item_name:'快速独有',category_level1:'侧板',category_level2:'',unit:'副',auxiliary_list:''}});
  assert.equal(sql(`SELECT quick_fee,formula_fee,error_count,quick_only_count FROM calc.get_attachment_dual_fee('${other}');`),'1049.19|0|0|1');
  assert.throws(()=>insert('QUICK_ONLY',{cost_rule_id:null,rule_version:null,formula_unit_cost:null,formula_amount:null}));
});
test('产品专用优先、通用回退、同级冲突拒绝',()=>{
  sql(`INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,category_level2,item_name,method,fixed_cost,source_file,source_sheet,source_row_no,raw_values)
    SELECT data_version,'R2',category_level1,category_level2,item_name,method,30,source_file,source_sheet,2,raw_values FROM calc.attachment_cost_rule WHERE rule_id=${ruleId};
    INSERT INTO calc.attachment_cost_rule_binding SELECT ${priceId},rule_id FROM calc.attachment_cost_rule WHERE import_key='R2';
    INSERT INTO calc.attachment_cost_rule_product SELECT rule_id,'JP' FROM calc.attachment_cost_rule WHERE import_key='R2';`);
  assert.notEqual(sql(`SELECT calc.resolve_attachment_cost_rule(${priceId},'JP');`),String(ruleId));
  assert.equal(sql(`SELECT calc.resolve_attachment_cost_rule(${priceId},'JP_WIDE_EXP');`),String(ruleId));
  sql("DELETE FROM calc.attachment_cost_rule_product WHERE product_code='JP';");
  assert.throws(()=>sql(`SELECT calc.resolve_attachment_cost_rule(${priceId},'JP');`));
});
test('正式生成包全量导入本地：226面价、62规则、264绑定及材质关系',()=>{
  file('database/attachment-v2/generated/03-stage-only.sql');
  file('database/attachment-v2/04a-stage-acceptance.sql');
  assert.equal(sql(`SELECT count(*) FROM calc.attachment_classification c JOIN calc.attachment_price p USING(attachment_price_id) WHERE p.data_version='${original.data_version}' AND (c.category_level2='' OR c.category_level3='');`),'0');
  const imported=JSON.parse(sql(`SELECT json_agg(json_build_object('key',import_key,'price',quick_face_price,'row',source_row_no) ORDER BY source_row_no) FROM calc.attachment_price WHERE data_version='${original.data_version}';`));
  assert.equal(imported.length,226);
  for(const row of imported) assert.equal(row.price,original.catalog.find(q=>q.import_key===row.key).price);
  assert.equal(sql("SELECT count(*) FROM calc.attachment_price WHERE is_active;"),'2');
  assert.equal(sql("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='HISTORY';"),'1');
  assert.equal(sql(`SELECT count(*) FROM calc.attachment_cost_rule WHERE data_version='${original.data_version}';`),'62');
  assert.equal(sql(`SELECT count(*) FROM calc.attachment_cost_rule_material m JOIN calc.attachment_cost_rule r USING(rule_id) WHERE r.data_version='${original.data_version}';`),'9');
  file('database/attachment-v2/04-validate.sql');
});
test('数据库按材质解析，旧两参调用拒绝猜测，保存时拒绝错误材质规则',()=>{
  const q=Number(sql(`SELECT attachment_price_id FROM calc.attachment_price WHERE data_version='${original.data_version}' AND source_row_no=208;`));
  const expected={SECC:6,SUS304:17.5,SUS316:17.5};
  for(const [material,cost] of Object.entries(expected)) {
    assert.equal(Number(sql(`SELECT fixed_cost FROM calc.attachment_cost_rule WHERE rule_id=calc.resolve_attachment_cost_rule(${q},'JP','${material}');`)),cost);
  }
  assert.throws(()=>sql(`SELECT calc.resolve_attachment_cost_rule(${q},'JP');`));
  const steelRule=Number(sql(`SELECT calc.resolve_attachment_cost_rule(${q},'JP','SECC');`));
  const stainlessRule=Number(sql(`SELECT calc.resolve_attachment_cost_rule(${q},'JP','SUS304');`));
  const id='33333333-3333-4333-8333-333333333333';
  const env={...environment,material_code:'SUS304'};
  sql(`INSERT INTO calc.attachment_quote_line(quote_line_id,quote_id,product_code,environment_snapshot) VALUES('${id}','NEW','JP',${json(env)});`);
  const values={quote_line_id:id,attachment_price_id:q,environment_snapshot:env,catalog_version:original.data_version,rule_version:original.data_version,quick_face_price:20,quick_amount:40,cost_rule_id:steelRule,formula_unit_cost:6,formula_amount:12,cost_snapshot:{item_name:'门限位器',category_level1:'控制柜附件',category_level2:'门限位器',unit:'件',auxiliary_list:''}};
  assert.throws(()=>insert('FIXED',values));
  const saved=insert('FIXED',{...values,cost_rule_id:stainlessRule,formula_unit_cost:17.5,formula_amount:35});
  assert.equal(sql(`SELECT quick_amount,formula_amount FROM calc.attachment_selection WHERE attachment_selection_id=${saved};`),'40|35');
  // A conflicting second rule for the same material must fail, never choose the first.
  sql(`INSERT INTO calc.attachment_cost_rule_material VALUES(${steelRule},'SUS304');`);
  assert.throws(()=>sql(`SELECT calc.resolve_attachment_cost_rule(${q},'JP','SUS304');`));
});
