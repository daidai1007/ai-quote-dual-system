// Real HTTP + owned disposable loopback PostgreSQL. Never application settings.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import net from 'node:net';
import ExcelJS from '@excel.js/exceljs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {PRICING_BASIS,quickOrderLineBreakdown,materialDifferenceAmount,manufacturingFormulaForItem,MANUFACTURING_COST_BASIS,moneyProduct,QUICK_FREIGHT_BASIS} from '../quick_discount_rules.mjs';
import {TAX_COST_BASIS,withTaxCostForItem} from '../tax_cost.mjs';

test('arbitrary thickness: original database formulas, 1.5mm parts only, unchanged cabinet face and undiscounted surcharge', {timeout:180000},async()=>{
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
    SELECT n,code,'SECC',800,1800,600,1000,1000 FROM (VALUES (1,'JS_SINGLE'),(2,'JA_SINGLE'),(3,'JE_SINGLE'),(4,'JP_SINGLE'),(5,'JM')) t(n,code);
    DROP FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date);
    CREATE FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date)
    RETURNS TABLE(quick_rule_id bigint,quick_total_cost numeric,match_method text,dimension_distance numeric,
      reference_width_mm numeric,reference_height_mm numeric,reference_depth_mm numeric)
    LANGUAGE sql AS $$ SELECT q.quick_rule_id,q.quick_total_cost,'LOCAL'::text,0::numeric,
      q.reference_width_mm,q.reference_height_mm,q.reference_depth_mm
      FROM calc.quick_quote_experience q WHERE q.product_code=$1 $$;`);
  pg.query(`INSERT INTO calc.material VALUES('SGCC',7.85);
    INSERT INTO calc.cabinet_material_catalog_version(data_version,source_file,source_sha256,status,default_waste_factor,activated_at)
      VALUES('local-weight-surcharge','LOCAL',repeat('0',64),'ACTIVE',1.2,now());
    INSERT INTO calc.cabinet_material_rule(data_version,family,body_thickness_profile_mm,profile_label,single_door_count,double_door_count,
      part_name,area_formula,sheet_thickness_mm,quantity_rule,fixed_material_code,source_sheet,source_row_no,source_column)
      SELECT 'local-weight-surcharge',family,1.5,'1.5mm baseline',1,0,part,area,thickness,'{"kind":"CONSTANT","value":1}'::jsonb,
        material,family,num,'A' FROM (VALUES('JS'),('JA'),('JE'),('JP'),('JM')) f(family)
      CROSS JOIN (VALUES('柜体','宽度*高度*0.000001',1.5::numeric,NULL::text,1),
        ('门板','1',2::numeric,NULL::text,2),('安装板','1',2.5::numeric,'SGCC',3)) p(part,area,thickness,material,num);`);
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
  const input=(code,thickness=2.375)=>({quote_id:`LOCAL-${code}-${thickness}`,product_code:code,material_code:'SECC',
    width_mm:800,height_mm:1800,depth_mm:600,quote_date:'2026-10-30',coating_type:'橘纹',
    single_door_count:1,double_door_count:0,waste_factor:1.2,cabinet_body_thickness_mm:thickness,
    material_unit_price_override:4.2,galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
    freight_fee:17,attachments:[],attachment_contract:2});
  let picked;
  for(const code of ['JS_SINGLE','JA_SINGLE','JE_SINGLE','JP_SINGLE','JM']){
    for(const thickness of [1.5,2,2.375,3.2]){
      const result=await call('/api/quotes/calculate-dual',input(code,thickness),token);
      assert.equal(result.status,200,JSON.stringify(result));
      assert.equal(result.body.quick_quote.base_price,1000);
      assert.equal(result.body.quick_quote.total_cost,1000);
      const parts=result.body.formula_cost.cabinet_material_part_details;
      assert.equal(parts.find(p=>p.part_name==='柜体').sheet_thickness_mm,thickness);
      assert.equal(parts.find(p=>p.part_name==='门板').sheet_thickness_mm,2);
      assert.equal(parts.find(p=>p.part_name==='安装板').sheet_thickness_mm,2.5);
      if(thickness>1.5){
        const pair=result.body.formula_cost.thickness_comparison;
        assert.equal(pair.weight_difference_kg,Math.round(1.44*(thickness-1.5)*7.85*1.2*1e8)/1e8);
      }else assert.equal(result.body.formula_cost.thickness_comparison,undefined);
      if(code==='JS_SINGLE'&&thickness===2.375)picked=result.body;
    }
  }
  assert.equal(pg.query("SELECT string_agg(DISTINCT sheet_thickness_mm::text,',' ORDER BY sheet_thickness_mm::text) FROM calc.cabinet_material_rule;"),'1.5,2,2.5');
  const matched_sizes=[{width_mm:800,height_mm:1800,depth_mm:600}];
  const rematch=await call('/api/quotes/rematch-quick',{quote_line_id:picked.quote_line_id,matched_sizes},token);
  assert.equal(rematch.status,200,JSON.stringify(rematch));assert.equal(rematch.body.quick_quote.base_price,1000);
  const cabinets=[input('JS_SINGLE'),input('JP_SINGLE',1.5)];
  const batch=await call('/api/quotes/calculate-ganged',{cabinets,attachment_payload:{...cabinets[0],
    width_mm:1600,ganged_cabinet_count:2,ganged_cabinets:cabinets}},token);
  assert.equal(batch.status,200,JSON.stringify(batch));assert.equal(batch.body.quick_quote.base_price,2000);
  assert.equal(batch.body.formula_cost.thickness_comparison.weight_difference_kg,11.8692);
  const item={...input('JS_SINGLE'),name:'任意料厚柜体',quantity:3,unit:'台',quick_discount:.5,
    pricing_basis:PRICING_BASIS,quote_line_id:picked.quote_line_id,attachments:[],thickness_surcharge_coefficient:12,
    quick:picked.quick_quote,formula:picked.formula_cost,manufacturing_cost_basis:MANUFACTURING_COST_BASIS,tax_cost_basis:TAX_COST_BASIS};
  const difference=materialDifferenceAmount(item);assert.equal(difference,142.43);
  const line=quickOrderLineBreakdown({quote:item.quick,attachments:[],discount:.5,cabinetQuantity:3,freightFee:17,materialDifference:difference});
  assert.equal(line.equivalentUnitTotal,659.43);assert.equal(line.lineTotal,1978.29);
  item.formula=withTaxCostForItem({...item,formula:manufacturingFormulaForItem(item)});
  item.quote_display={name:item.name,specification:'800*600*1800',quantity:3,unit:'台',discount:.5,
    unit_price:659.43,total:1978.29,attachment_face_price:0,material_difference:difference,thickness_surcharge:difference,
    quick_base_price:1000,quick_attachment_fee:0,quick_total_cost:1000,attachment_source:'popup_v1',attachments:[],remark:''};
  const payload={quote_id:item.quote_id,company_name:'本机合成客户',quote_date:'2026-10-30',order_nature:'EXTERNAL',items:[item]};
  for(const route of ['/api/quotes/confirm-check','/api/quotes/confirm']){
    const result=await call(route,payload,token);assert.equal(result.status,200,JSON.stringify(result));
  }
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,thickness_surcharge_coefficient}' FROM calc.quote_document;"),'12');
  assert.equal(pg.query("SELECT document_payload#>>'{items,0,quote_display,material_difference}' FROM calc.quote_document;"),'142.43');
  const output=await request('/api/quotes/export',payload,token);
  assert.equal(output.status,200,output.status===200?'':await output.text());
  const book=new ExcelJS.Workbook();await book.xlsx.load(Buffer.from(await output.arrayBuffer()));
  assert.equal(book.getWorksheet('报价').getCell('F11').value,659.43);
  const publicQuote=book.getWorksheet('报价2');
  assert.equal(publicQuote.getCell('F11').value.formula,"'报价'!F11");
  assert.equal(publicQuote.getCell('F11').value.result,659.43);
  assert.equal(publicQuote.getCell('G11').value.result,1978.29);
  const total=book.getWorksheet('报价').getCell('G11').value;assert.equal(total?.result??total,1978.29);
  const visible=[];book.getWorksheet('报价').eachRow(row=>row.eachCell(cell=>visible.push(cell.value)));
  assert.ok(visible.includes(142.43),'surcharge remains an original-price detail, not part of discounted cabinet face');
  const tampered=structuredClone(payload);Object.assign(tampered.items[0].quote_display,{material_difference:0,unit_price:517,total:1551});
  const rejected=await call('/api/quotes/confirm-check',tampered,token);assert.equal(rejected.status,422,JSON.stringify(rejected));
  pg.query('UPDATE calc.quick_quote_experience SET quick_base_price=9999,quick_total_cost=9999; UPDATE calc.cabinet_material_rule SET sheet_thickness_mm=7;');
  const again=await request('/api/quotes/export',payload,token);assert.equal(again.status,200,again.status===200?'':await again.text());
  const frozen=new ExcelJS.Workbook();await frozen.xlsx.load(Buffer.from(await again.arrayBuffer()));
  assert.equal(frozen.getWorksheet('报价').getCell('F11').value,659.43);
 }catch(error){
  console.error(pg.query("SELECT pg_read_file('../postgres.log');"));throw error;
 }finally{
  if(child&&child.exitCode===null){const ended=once(child,'exit');child.kill();await ended;}
  await pg.close();
 }
});
