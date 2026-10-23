// Real API + a fresh, owned loopback PostgreSQL cluster; synthetic orders only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import net from 'node:net';
import ExcelJS from '@excel.js/exceljs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

test('calculation preflight distinguishes V2 attachment IDs from legacy names', {timeout:300000}, async t => {
  const pg = await startLocalPostgres();
  let child;
  try {
    for (const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
      'database/attachment-v2/web/01-prepare.sql', 'database/attachment-v2/web/02-stage.sql',
      'tests/fixtures/attachment_api_base_stub.sql', 'database/migrations/cabinet_material_v2.sql',
      'database/migrations/cabinet_spray_v2.sql', 'database/migrations/cabinet_labor_v1.sql',
      'database/migrations/cabinet_auxiliary_v1.sql', 'database/migrations/cabinet_auxiliary_v2.sql',
      'database/migrations/cabinet_auxiliary_v3.sql', 'database/migrations/quote_scheme_center_v1.sql',
      'database/migrations/quote_name_scope_v1.sql']) {
      pg.query(await readFile(new URL('../' + file, import.meta.url), 'utf8'));
    }
    pg.query('CREATE TABLE calc.dual_quote_result(quote_id text PRIMARY KEY);');
    const version = pg.query("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
    assert.match(version, /^xlsx-[a-f0-9]{16}-r[0-9]+$/);
    pg.query(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${version}'); COMMIT;`);

    const listener = net.createServer();
    listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
    const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
    const env = {...process.env, AI_QUOTE_API_HOST:'127.0.0.1', PORT:String(port),
      AI_QUOTE_API_KEY:'local-attachment-test', PSQL_PATH:pg.connection.psql,
      AI_QUOTE_DB_HOST:'127.0.0.1', AI_QUOTE_DB_PORT:String(pg.connection.port),
      AI_QUOTE_DB_USER:pg.connection.user, AI_QUOTE_DB_NAME:'postgres'};
    for (const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS',
      'PGPASSWORD','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','RENDER',
      'AI_QUOTE_PRINCIPALS_JSON','AI_QUOTE_ATTACHMENT_V2_VERSION','AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED']) delete env[key];
    env.PGSSLMODE='disable'; env.PGCONNECT_TIMEOUT='5';
    child = spawn(process.execPath, ['api/server.mjs'], {cwd:new URL('../', import.meta.url),
      env, windowsHide:true, stdio:['ignore','pipe','pipe']});
    let errors=''; child.stdout.resume(); child.stderr.on('data', chunk => { errors += chunk.toString(); });
    const base = `http://127.0.0.1:${port}`;
    let ready=false;
    for (let i=0;i<100;i++) {
      try { if ((await fetch(base+'/health')).ok) { ready=true; break; } } catch {}
      if (child.exitCode!==null) throw new Error('Local API stopped: '+errors.slice(-1500));
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    assert.ok(ready, 'Local API startup timed out');
    const request = async (route, body, token, extra={}) => fetch(base+route, {method:body?'POST':'GET',
      headers:{'x-ai-quote-key':'local-attachment-test','Content-Type':'application/json',
        ...(token?{Authorization:'Bearer '+token}:{}),...extra}, body:body?JSON.stringify(body):undefined});
    const call = async (...args) => {const r=await request(...args); return {status:r.status,body:await r.json()};};
    const login=await call('/api/name-login',{name:'附件回归人员甲'});
    const other=await call('/api/name-login',{name:'附件回归人员乙'});
    assert.equal(login.status,200); assert.equal(other.status,200);
    const token=login.body.token;
    const catalog=await call('/api/attachments/catalog?v=2',undefined,token);
    assert.equal(catalog.status,200,JSON.stringify(catalog));
    const limiter=catalog.body.items.find(row=>row.source_row_no===208);
    assert.ok(limiter);
    const cabinet=(quote_id,width_mm=800)=>({quote_id,product_code:'JP_SINGLE',material_code:'SECC',
      model_code:`${width_mm}*600*2100`,width_mm,height_mm:2100,depth_mm:600,quote_date:'2026-10-23',
      coating_type:'橘纹',attachments:[],material_unit_price_override:4.2,
      galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
      surface_treatment_unit_price_override:26});
    const selection={attachment_price_id:limiter.attachment_price_id,quantity:2,manual_inputs:{}};
    const v2={...cabinet('LOCAL-V2-SINGLE'),attachment_contract:2,attachments:[selection]};
    let single, batchResult, batch;

    await t.test('unnamed ID-only selection succeeds on single-cabinet HTTP route', async()=>{
      assert.equal(selection.item_name,undefined); assert.equal(selection.model_code,undefined);
      single=await call('/api/quotes/calculate-dual',v2,token);
      assert.equal(single.status,200,JSON.stringify(single));
      assert.equal(single.body.attachment_contract,2);
      assert.equal(single.body.attachments[0].item_name,'门限位器');
      assert.equal(single.body.attachments[0].formula_amount,12);
      assert.equal(single.body.attachments[0].quick_amount,40);
      assert.ok(single.body.quote_line_id);
    });

    await t.test('automatic fixed bases keep their ID, child index and amount in streamed batch', async()=>{
      const cabinets=[cabinet('LOCAL-V2-BATCH-0',1000),cabinet('LOCAL-V2-BATCH-1',800)];
      const bases=cabinets.map((row,ganged_cabinet_index)=>{
        const item=catalog.body.items.find(item=>item.item_name==='固定底座'&&Number(item.width_mm)===row.width_mm
          &&Number(item.depth_mm)===600&&Number(item.height_mm)===100);
        assert.ok(item,'Missing synthetic base selection for '+row.width_mm);
        return {attachment_price_id:item.attachment_price_id,quantity:1,ganged_cabinet_index,manual_inputs:{底座高度:100}};
      });
      batch={cabinets,attachment_payload:{...cabinets[0],width_mm:1800,attachment_contract:2,
        ganged_cabinet_count:2,ganged_cabinets:cabinets,attachments:bases}};
      const response=await request('/api/quotes/calculate-ganged',batch,token,{accept:'application/x-ndjson'});
      assert.equal(response.status,200);
      const events=(await response.text()).trim().split('\n').map(JSON.parse);
      assert.equal(events.at(-1).type,'result',JSON.stringify(events.at(-1)));
      batchResult=events.at(-1).result;
      assert.equal(batchResult.attachment_contract,2); assert.equal(batchResult.attachments.length,2);
      assert.deepEqual(batchResult.attachments.map(row=>row.ganged_cabinet_index),[0,1]);
      assert.deepEqual(batchResult.attachments.map(row=>row.attachment_price_id),bases.map(row=>row.attachment_price_id));
      const amounts=batchResult.attachments.reduce((sum,row)=>sum+row.quick_amount,0);
      assert.equal(batchResult.quick_quote.attachment_fee,amounts);
      assert.equal(batchResult.quick_quote.total_cost,400+amounts);
      assert.equal(pg.query('SELECT count(*) FROM calc.local_base_probe;'),'0','child writes are rolled back');
      assert.equal(pg.query("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='LOCAL-V2-BATCH-0';"),'2');
    });

    await t.test('fallback ganged snapshot accepts the same ID-only payload', async()=>{
      const input={...batch.attachment_payload,quote_id:'LOCAL-V2-FALLBACK',base_result:batchResult};
      const response=await call('/api/attachments/snapshot-ganged',input,token);
      assert.equal(response.status,200,JSON.stringify(response));
      assert.equal(response.body.quick_quote.total_cost,batchResult.quick_quote.total_cost);
    });

    await t.test('saved snapshot, confirmation and actual Excel export preserve prices and customer', async()=>{
      for (const [kind,input,result] of [['SINGLE',v2,single.body],['GANGED',{
        ...batch.attachment_payload,ganged_cabinet_inputs:batch.cabinets},batchResult]]) {
        const document={quote_id:'LOCAL-V2-DOCUMENT-'+kind,company_code:'LOCAL-V2-CUSTOMER-'+kind,
          company_name:'合成附件回归客户-'+kind,quote_date:v2.quote_date,
          items:[{...input,quote_line_id:result.quote_line_id,attachments:result.attachments,
            quantity:1,formula:result.formula_cost,quick:result.quick_quote}]};
        const saved=await call('/api/quotes/confirm',document,token);
        assert.equal(saved.status,200,JSON.stringify(saved));
        const reopened=await call('/api/company-history/match',{...input,company_code:document.company_code},token);
        assert.equal(reopened.status,200,JSON.stringify(reopened));
        assert.equal(reopened.body.payload.quick.total_cost,result.quick_quote.total_cost);
        assert.deepEqual(reopened.body.payload.attachments.map(row=>row.attachment_selection_id),
          result.attachments.map(row=>row.attachment_selection_id));
        const exported=await request('/api/quotes/export',document,token);
        assert.equal(exported.status,200,exported.status===200?'':await exported.text());
        const workbook=new ExcelJS.Workbook(); await workbook.xlsx.load(Buffer.from(await exported.arrayBuffer()));
        const cells=[]; workbook.eachSheet(sheet=>sheet.eachRow(row=>row.eachCell(cell=>cells.push(cell.value))));
        assert.ok(cells.some(value=>String(value).includes(document.company_name)));
        assert.ok(cells.includes(result.quick_quote.total_cost));
      }
    });

    await t.test('invalid V2 input and legacy nameless rows fail before ownership reservation', async()=>{
      const badRows=[{...selection,attachment_price_id:null},{...selection,attachment_price_id:0},
        {...selection,quantity:0},{...selection,manual_inputs:[]},{...selection,attachment_price_sign:0},
        {...selection,ganged_cabinet_index:20}];
      for (let index=0;index<badRows.length;index++) {
        const input={...v2,quote_id:'LOCAL-INVALID-'+index,attachments:[badRows[index]]};
        const response=await call('/api/quotes/calculate-dual',input,token);
        assert.equal(response.status,400,JSON.stringify(response));
        assert.equal(pg.query(`SELECT count(*) FROM calc.quote_name_owner WHERE resource_key='${input.quote_id}';`),'0');
      }
      const legacy=await call('/api/quotes/calculate-dual',{...v2,quote_id:'LOCAL-LEGACY',attachment_contract:undefined},token);
      assert.equal(legacy.status,400); assert.match(legacy.body.message,/requires model_code or item_name/);
      const invalidBatch=structuredClone(batch);
      invalidBatch.cabinets.forEach((row,index)=>{row.quote_id='LOCAL-INVALID-BATCH-'+index;});
      invalidBatch.attachment_payload.quote_id=invalidBatch.cabinets[0].quote_id;
      invalidBatch.attachment_payload.attachments[0].attachment_price_id=null;
      assert.equal((await call('/api/quotes/calculate-ganged',invalidBatch,token)).status,400);
      assert.equal(pg.query("SELECT count(*) FROM calc.quote_name_owner WHERE resource_key LIKE 'LOCAL-INVALID-BATCH-%';"),'0');
      const missing=await call('/api/quotes/calculate-dual',{...v2,quote_id:'LOCAL-UNKNOWN',attachments:[{...selection,attachment_price_id:9999999}]},token);
      assert.ok(missing.status>=400); assert.match(missing.body.message,/不属于当前目录/);
    });

    await t.test('another person cannot reuse the successful private quote identifier', async()=>{
      const response=await call('/api/quotes/calculate-dual',v2,other.body.token);
      assert.equal(response.status,403);
    });
  } finally {
    if (child&&child.exitCode===null) {const exited=once(child,'exit'); child.kill(); await exited;}
    await pg.close();
  }
});
