// Only a disposable loopback cluster; never run against production credentials.
import assert from 'node:assert/strict';
import test from 'node:test';
import {execFileSync, spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const db = `ganged_performance_test_${Date.now()}`, psql = 'G:/PostgreSQL/18/bin/psql.exe';
const sql = (source, database=db) => execFileSync(psql, ['-X','-w','-h','127.0.0.1','-p','55439','-U','attachment_test',
  '-d',database,'-v','ON_ERROR_STOP=1','-A','-t','-q'], {input:source,encoding:'utf8',stdio:['pipe','pipe','pipe']}).trim();
const file = relative => sql(fs.readFileSync(path.join(root,relative),'utf8'));

test('real batch HTTP API: independent material weights, two bases, streamed phases, single immutable snapshot', async () => {
  let child;
  sql(`CREATE DATABASE ${db};`, 'postgres');
  try {
    for (const f of ['tests/fixtures/attachment_online_schema_20260911.sql','database/attachment-v2/web/01-prepare.sql',
      'database/attachment-v2/web/02-stage.sql','tests/fixtures/attachment_api_base_stub.sql',
      'database/migrations/cabinet_material_v2.sql','database/cabinet-material/web/02-stage.sql']) file(f);
    const stagedVersion=sql("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
    assert.match(stagedVersion, /^xlsx-[a-f0-9]{16}-r[0-9]+$/);
    sql(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${stagedVersion}'); COMMIT;
      SELECT calc.activate_cabinet_material_catalog_v2('cabinet-material-4f8bf726efa6568d-v2');`);
    const reserve=net.createServer(); await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
    const port=reserve.address().port; await new Promise(resolve=>reserve.close(resolve));
    child=spawn(process.execPath, ['api/server.mjs'], {cwd:root,windowsHide:true,env:{...process.env,
      DATABASE_URL:'',PGPASSWORD:'',RENDER:'',PORT:String(port),PSQL_PATH:psql,AI_QUOTE_API_KEY:'',AI_QUOTE_API_HOST:'127.0.0.1',
      AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:'55439',AI_QUOTE_DB_USER:'attachment_test',AI_QUOTE_DB_NAME:db}});
    const log=[]; child.stdout.on('data',data=>log.push(String(data)));
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('local API startup timeout')),8000);
      child.stdout.on('data',data=>{if(String(data).includes('listening')){clearTimeout(timer);resolve();}});child.once('error',reject);});
    const catalog=await (await fetch(`http://127.0.0.1:${port}/api/attachments/catalog?v=2`)).json();
    const cabinets=[1000,800].map((width,index)=>({quote_id:`BATCH-${index}`,product_code:'JP_SINGLE',material_code:'SECC',
      width_mm:width,height_mm:2100,depth_mm:600,quote_date:'2026-10-09',coating_type:'橘纹',
      single_door_count:1,double_door_count:0,waste_factor:1.2,cabinet_body_thickness_mm:1.5,
      material_unit_price_override:4.2,galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
      attachments:[]}));
    const bases=cabinets.map((cabinet,ganged_cabinet_index)=>{
      const item=catalog.items.find(item=>item.item_name==='固定底座' && Number(item.width_mm)===cabinet.width_mm
        && Number(item.depth_mm)===600 && Number(item.height_mm)===100);
      assert.ok(item, `missing fixed base ${cabinet.width_mm}x600x100`);
      return {attachment_price_id:item.attachment_price_id,quantity:1,ganged_cabinet_index,
        manual_inputs:{'底座高度':100}};
    });
    const input={cabinets,attachment_payload:{...cabinets[0],quote_id:'BATCH-0',width_mm:1800,
      ganged_cabinet_count:2,ganged_cabinets:cabinets,attachments:bases,attachment_contract:2}};
    const response=await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-ganged`,{method:'POST',
      headers:{'content-type':'application/json',accept:'application/x-ndjson','x-quote-request-id':'batch-database-trace'},body:JSON.stringify(input)});
    assert.equal(response.status,200);
    const events=(await response.text()).trim().split('\n').map(JSON.parse);
    assert.equal(events.at(-1).type,'result',JSON.stringify(events.at(-1)));
    const result=events.at(-1).result;
    assert.equal(result.ganged_batch_contract,1);
    assert.equal(result.attachment_contract,2);
    assert.equal(result.attachments.length,2);
    assert.deepEqual(result.attachments.map(row=>row.ganged_cabinet_index),[0,1]);
    const weights=result.formula_cost.ganged_cabinet_costs.map(row=>row.formula_cost.corrected_material_weight_kg);
    assert.ok(weights[0]>weights[1] && weights[1]>0);
    assert.equal(result.formula_cost.corrected_material_weight_kg,weights[0]+weights[1]);
    assert.deepEqual(result.formula_cost.ganged_cabinet_costs.map(row=>row.width_mm),[1000,800]);
    assert.equal(sql('SELECT count(*) FROM calc.local_base_probe;'),'0','child writes must be rolled back');
    assert.equal(sql('SELECT count(*) FROM calc.attachment_quote_line;'),'1','only the final aggregate is snapshotted');
    assert.equal(sql("SELECT count(*) FROM calc.attachment_selection WHERE quote_id='BATCH-0';"),'2');
    const stages=events.filter(event=>event.type==='progress').map(event=>event.stage);
    assert.ok(stages.includes('cabinet') && stages.includes('attachments') && stages.includes('snapshot'));
    assert.match(log.join(''),/batch_read_reused/);
    assert.match(log.join(''),/batch-database-trace/);
    assert.match(log.join(''),/child_calculation/);
  } finally {
    if(child){child.kill();await new Promise(resolve=>child.exitCode!=null?resolve():child.once('exit',resolve));}
    sql(`DROP DATABASE ${db};`, 'postgres');
  }
});
