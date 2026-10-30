import {quickQuotationAmount} from './quotation_layout_reader.mjs';
// Real HTTP + owned disposable loopback PostgreSQL. Never application settings.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import net from 'node:net';
import ExcelJS from '@excel.js/exceljs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown,manufacturingFormulaForItem,MANUFACTURING_COST_BASIS,moneyProduct,QUICK_FREIGHT_BASIS} from '../quick_discount_rules.mjs';
import {TAX_COST_BASIS,withTaxCostForItem} from '../tax_cost.mjs';

test('2mm cabinet face: real HTTP calculations, manual rematch, mixed gang, frozen confirmation and Excel export', {timeout:180000},async()=>{
 const pg=await startLocalPostgres();let child;
 try{
  for(const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
    'database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql',
    'tests/fixtures/attachment_api_base_stub.sql','database/migrations/cabinet_material_v2.sql',
    'database/migrations/cabinet_spray_v2.sql','database/migrations/cabinet_labor_v1.sql',
    'database/migrations/cabinet_auxiliary_v1.sql','database/migrations/cabinet_auxiliary_v2.sql',
    'database/migrations/cabinet_auxiliary_v3.sql','database/migrations/quote_scheme_center_v1.sql',
    'database/migrations/quote_name_scope_v1.sql'])pg.query(await readFile(new URL('../'+file,import.meta.url),'utf8'));
  const version=pg.query("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
  pg.query(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${version}'); COMMIT;`);
  pg.query(`CREATE TABLE calc.dual_quote_result(quote_id text PRIMARY KEY);
    ALTER TABLE calc.quick_quote_experience ADD COLUMN quick_total_cost numeric;
    DELETE FROM calc.quick_quote_experience;
    INSERT INTO calc.quick_quote_experience(quick_rule_id,product_code,material_code,reference_width_mm,reference_height_mm,reference_depth_mm,quick_base_price,quick_total_cost)
    SELECT n,code,'SECC',800,1800,600,200,200 FROM (VALUES (1,'JS_SINGLE'),(2,'JA_SINGLE'),(3,'JE_SINGLE'),(4,'JP_SINGLE')) t(n,code);
    DROP FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date);
    CREATE FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date)
    RETURNS TABLE(quick_rule_id bigint,quick_total_cost numeric,match_method text,dimension_distance numeric,
      reference_width_mm numeric,reference_height_mm numeric,reference_depth_mm numeric)
    LANGUAGE sql AS $$ SELECT q.quick_rule_id,q.quick_total_cost,'LOCAL'::text,0::numeric,
      q.reference_width_mm,q.reference_height_mm,q.reference_depth_mm
      FROM calc.quick_quote_experience q WHERE q.product_code=$1 $$;`);
  const listener=net.createServer();listener.listen(0,'127.0.0.1');await once(listener,'listening');
  const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
  const env={...process.env,AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),AI_QUOTE_API_KEY:'standalone-test',
    PSQL_PATH:pg.connection.psql,AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:String(pg.connection.port),
    AI_QUOTE_DB_USER:pg.connection.user,AI_QUOTE_DB_NAME:'postgres'};
  for(const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS','PGPASSWORD','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','RENDER','AI_QUOTE_PRINCIPALS_JSON','AI_QUOTE_ATTACHMENT_V2_VERSION','AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED'])delete env[key];
  env.PGSSLMODE='disable';env.PGCONNECT_TIMEOUT='5';
  child=spawn(process.execPath,['api/server.mjs'],{cwd:new URL('../',import.meta.url),env,windowsHide:true,stdio:['ignore','pipe','pipe']});
  let errors='';child.stdout.resume();child.stderr.on('data',chunk=>errors+=chunk.toString());
  const base=`http://127.0.0.1:${port}`;
  for(let n=0;n<100;n++){try{if((await fetch(base+'/health')).ok)break;}catch{}if(child.exitCode!==null)throw Error(errors);await new Promise(resolve=>setTimeout(resolve,50));}
  const request=(route,body,token)=>fetch(base+route,{method:body?'POST':'GET',headers:{'x-ai-quote-key':'standalone-test','Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});
  const call=async(...args)=>{const response=await request(...args);return {status:response.status,body:await response.json()};};
  const login=await call('/api/name-login',{name:'独立附件回归甲'});assert.equal(login.status,200,JSON.stringify(login));
  const token=login.body.token;
  const catalog=await call('/api/attachments/catalog?v=2',undefined,token);assert.equal(catalog.status,200);
  const input=(code,thickness=2)=>({quote_id:`LOCAL-${code}-${thickness}`,product_code:code,material_code:'SECC',
    width_mm:800,height_mm:1800,depth_mm:600,quote_date:'2026-10-30',coating_type:'橘纹',
    single_door_count:1,double_door_count:0,waste_factor:1.2,cabinet_body_thickness_mm:thickness,
    material_unit_price_override:4.2,galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
    freight_fee:17,attachments:[],attachment_contract:2});
  let picked;
  for(const code of ['JS_SINGLE','JA_SINGLE','JE_SINGLE','JP_SINGLE']){
    for(const thickness of [1.5,2,2.5]){
      const result=await call('/api/quotes/calculate-dual',input(code,thickness),token);
      assert.equal(result.status,200,JSON.stringify(result));
      const expected=code==='JP_SINGLE'||thickness!==2?200:240;
      assert.equal(result.body.quick_quote.base_price,expected,`${code} ${thickness}`);
      assert.equal(result.body.quick_quote.attachment_fee,0);
      assert.equal(result.body.quick_quote.total_cost,expected);
      if(code==='JS_SINGLE'&&thickness===2)picked=result.body;
    }
  }
  const matched_sizes=[{width_mm:800,height_mm:1800,depth_mm:600}];
  const rematch=await call('/api/quotes/rematch-quick',{quote_line_id:picked.quote_line_id,matched_sizes},token);
  assert.equal(rematch.status,200,JSON.stringify(rematch));assert.equal(rematch.body.quick_quote.base_price,240);
  const repeated=await call('/api/quotes/rematch-quick',{quote_line_id:rematch.body.quote_line_id,matched_sizes},token);
  assert.equal(repeated.status,200,JSON.stringify(repeated));assert.equal(repeated.body.quick_quote.base_price,240);
  const cabinets=[input('JS_SINGLE'),input('JP_SINGLE')];
  const batch=await call('/api/quotes/calculate-ganged',{cabinets,attachment_payload:{...cabinets[0],
    width_mm:1600,ganged_cabinet_count:2,ganged_cabinets:cabinets}},token);
  assert.equal(batch.status,200,JSON.stringify(batch));assert.equal(batch.body.quick_quote.base_price,440);
  assert.deepEqual(batch.body.ganged_cabinet_results.map(c=>c.quick_quote.base_price),[240,200]);
  const item={...input('JS_SINGLE'),name:'2mm柜体',quantity:3,unit:'台',quick_discount:.5,
    pricing_basis:PRICING_BASIS,quote_line_id:picked.quote_line_id,attachments:[],
    quick:picked.quick_quote,formula:picked.formula_cost};
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:[],discount:.5,cabinetQuantity:3,freightFee:17});
  assert.equal(line.equivalentUnitTotal,137);assert.equal(line.lineTotal,411);
  item.quote_display={name:item.name,specification:'800*600*1800',quantity:3,unit:'台',discount:.5,
    unit_price:137,total:411,attachment_face_price:0,material_difference:0,quick_base_price:240,
    quick_attachment_fee:0,quick_total_cost:240,attachment_source:'popup_v1',attachments:[],remark:''};
  const payload={quote_id:item.quote_id,company_name:'本机合成客户',quote_date:'2026-10-30',order_nature:'EXTERNAL',items:[item]};
  for(const route of ['/api/quotes/confirm-check','/api/quotes/confirm']){
    const response=await call(route,payload,token);assert.equal(response.status,200,JSON.stringify(response));
  }
  const frozen=pg.query("SELECT document_payload#>>'{items,0,quick,base_price}' FROM calc.quote_document;");
  assert.equal(frozen,'240');
  const output=await request('/api/quotes/export',payload,token);
  assert.equal(output.status,200,output.status===200?'':await output.text());
  const book=new ExcelJS.Workbook();await book.xlsx.load(Buffer.from(await output.arrayBuffer()));
  assert.deepEqual(book.worksheets.map(s=>s.name),['成本','报价','成本明细','附件双报价明细']);
  const values=[];book.getWorksheet('报价').eachRow(row=>row.eachCell(cell=>values.push(cell.value)));
  assert.ok(values.includes(137),JSON.stringify(values));assert.equal(quickQuotationAmount(book.getWorksheet('报价').getCell('G11')),411);
  // Directory edits after confirmation must never reprice its frozen 2mm base.
  pg.query('UPDATE calc.quick_quote_experience SET quick_base_price=999,quick_total_cost=999;');
  const again=await request('/api/quotes/export',payload,token);assert.equal(again.status,200,again.status===200?'':await again.text());
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,quick,base_price}' FROM calc.quote_document;"),'240');
 }catch(error){
  console.error(pg.query("SELECT pg_read_file('../postgres.log');"));
  throw error;
 }finally{
  if(child&&child.exitCode===null){const ended=once(child,'exit');child.kill();await ended;}
  await pg.close();
 }
});

