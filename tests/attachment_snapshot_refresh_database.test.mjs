// Targeted SQL execution in a new disposable loopback-only PostgreSQL cluster.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {createAttachmentService,sqlValue} from '../api/attachment_service.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const enabled=process.env.ATTACHMENT_REFRESH_DB_TEST==='1';
test('merged refresh SQL executes with real rules, guards, deductions and immutable old snapshots',
  {skip:!enabled,timeout:90000},async()=>{
  const folder=fs.mkdtempSync(path.join(root,'.codex-tmp','attachment-refresh-pg-'));
  const data=path.join(folder,'data'),bin='G:/PostgreSQL/18/bin';
  const childEnv={...process.env,PGCLIENTENCODING:'UTF8'};
  for(const key of ['PGSERVICE','PGSERVICEFILE','PGPASSWORD','PGOPTIONS'])delete childEnv[key];
  const run=(exe,args,input)=>execFileSync(path.join(bin,exe),args,{input,encoding:'utf8',windowsHide:true,
    env:childEnv,timeout:30000,stdio:exe==='pg_ctl.exe'?'ignore':['pipe','pipe','pipe']})?.trim()??'';
  const reserve=net.createServer();
  await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;
  await new Promise(resolve=>reserve.close(resolve));
  run('initdb.exe',['-D',data,'-U','attachment_test','-A','trust','--encoding=UTF8','--no-locale']);
  try {
    run('pg_ctl.exe',['-D',data,'-l',path.join(folder,'server.log'),'-w','start','-o',`-h 127.0.0.1 -p ${port}`]);
    const sql=text=>run('psql.exe',['-X','-w','-h','127.0.0.1','-p',String(port),'-U','attachment_test',
      '-d','postgres','-v','ON_ERROR_STOP=1','-A','-t','-q'],text);
    for(const file of ['tests/fixtures/attachment_online_schema_20260911.sql',
      'database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql',
      'tests/fixtures/attachment_api_base_stub.sql'])sql(fs.readFileSync(path.join(root,file),'utf8'));
    const stagedVersion=sql("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
    sql(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2(${sqlValue(stagedVersion)}); COMMIT;`);
    const queries=[];
    const service=createAttachmentService({env:{},runPsql:async text=>{queries.push(text);return sql(text);},
      calculateBase:async()=>({formula_cost:{material_cost:100,auxiliary_cost:10,labor_cost:20,
        spray_cost:15,management_fee:5,total_cost:150,attachment_fee:0},
        quick_quote:{base_price:500,total_cost:500,attachment_fee:0}})});
    const catalog=await service.catalog();
    const glass=catalog.items.find(row=>row.item_name==='玻璃门'&&row.category_level1==='控制柜附件');
    const board=catalog.items.find(row=>row.item_name==='安装板'&&row.category_level1==='安装板');
    assert.ok(glass&&board);
    const input={quote_id:'LOCAL_REFRESH',product_code:'JP_SINGLE',material_code:'SECC',width_mm:800,
      height_mm:1800,depth_mm:400,coating_type:'橘纹',quote_date:'2026-10-13',material_unit_price_override:4.2,
      attachments:[{attachment_price_id:glass.attachment_price_id,quantity:1,manual_inputs:{}}]};
    const old=await service.calculate(input);
    assert.equal(old.attachments[0].status,'ERROR');
    const frozen=()=>sql(`SELECT jsonb_build_object('environment',l.environment_snapshot,
      'rows',(SELECT jsonb_agg(s.cost_snapshot ORDER BY attachment_selection_id)
        FROM calc.attachment_selection s WHERE s.quote_line_id=l.quote_line_id))
      FROM calc.attachment_quote_line l WHERE l.quote_line_id='${old.quote_line_id}'::uuid;`);
    const before=frozen();
    queries.length=0;
    const fresh=await service.recalculateLine({quote_line_id:old.quote_line_id,attachments:[
      {...input.attachments[0],manual_inputs:{玻璃门宽度:400,玻璃门高度:400}}]});
    assert.equal(queries.length,2);
    assert.equal(fresh.attachments[0].formula_amount,8.8);
    // Legacy base carries a fixed fee of 5. A fresh result recomputes the
    // approved 6% on 100+10+20+15+8.80, without rewriting the old snapshot.
    assert.equal(fresh.formula_cost.management_fee,9.23);
    assert.equal(fresh.formula_cost.management_fee_rate,.06);
    assert.equal(fresh.formula_cost.total_cost,163.03);
    assert.notEqual(fresh.quote_line_id,old.quote_line_id);
    assert.equal(frozen(),before);
    queries.length=0;
    await assert.rejects(service.recalculateLine({quote_line_id:old.quote_line_id,attachments:input.attachments}),
      error=>error.statusCode===422);
    assert.equal(queries.length,1);
    queries.length=0;
    const deduction=await service.recalculateLine({quote_line_id:old.quote_line_id,attachments:[
      {attachment_price_id:board.attachment_price_id,quantity:2,attachment_price_sign:-1,manual_inputs:{}}]});
    assert.equal(queries.length,2);
    assert.ok(deduction.attachments[0].formula_amount<0);
    assert.ok(deduction.attachments[0].quick_amount<0);
    assert.equal(deduction.attachments[0].quantity,2);
    assert.equal(frozen(),before);
    const empty=await service.recalculateLine({quote_line_id:old.quote_line_id,attachments:[]});
    assert.deepEqual(empty.attachments,[]);
    assert.equal(empty.formula_cost.management_fee,8.7);
    assert.equal(empty.formula_cost.total_cost,153.7);
  } finally {
    if(fs.existsSync(path.join(data,'postmaster.pid')))run('pg_ctl.exe',['-D',data,'-w','stop','-m','fast']);
    // Never remove an unverified directory or a possibly running cluster.
    if(!fs.existsSync(path.join(data,'postmaster.pid'))
      &&path.dirname(folder)===path.join(root,'.codex-tmp')&&path.basename(folder).startsWith('attachment-refresh-pg-'))
      fs.rmSync(folder,{recursive:true,force:true});
  }
});
