// This test starts a new loopback-only cluster. Never use a cloud connection.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const bin=process.env.MANAGEMENT_TEST_PG_BIN||'G:/PostgreSQL/18/bin';
test('current SQL replaces old functions, is repeatable and leaves old quotations untouched',
  {skip:!fs.existsSync(path.join(bin,'initdb.exe')),timeout:90000},async()=>{
  const folder=fs.mkdtempSync(path.join(root,'.codex-tmp','management-fee-pg-'));
  const data=path.join(folder,'data');
  const env={...process.env,PGCLIENTENCODING:'UTF8'};
  for(const key of ['PGSERVICE','PGSERVICEFILE','PGPASSWORD','PGOPTIONS','DATABASE_URL'])delete env[key];
  const run=(exe,args,input)=>execFileSync(path.join(bin,exe),args,{input,env,encoding:'utf8',windowsHide:true,
    timeout:30000,stdio:exe==='pg_ctl.exe'?'ignore':['pipe','pipe','pipe']})?.trim()??'';
  const reserve=net.createServer();
  await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;
  await new Promise(resolve=>reserve.close(resolve));
  run('initdb.exe',['-D',data,'-U','management_test','-A','trust','--encoding=UTF8','--no-locale']);
  try {
    run('pg_ctl.exe',['-D',data,'-l',path.join(folder,'server.log'),'-w','start','-o',`-h 127.0.0.1 -p ${port}`]);
    const sql=text=>run('psql.exe',['-X','-w','-h','127.0.0.1','-p',String(port),'-U','management_test',
      '-d','postgres','-v','ON_ERROR_STOP=1','-A','-t','-q'],text);
    const file=relative=>sql(fs.readFileSync(path.join(root,relative),'utf8'));
    sql('CREATE SCHEMA calc; CREATE TABLE calc.dual_quote_result(id integer,formula_management_fee numeric,formula_total_cost numeric); INSERT INTO calc.dual_quote_result VALUES(1,999,8888);');
    file('database/migrations/create_total_cost_calculation.sql');
    file('database/migrations/create_total_cost_by_spray_cost.sql');
    file('database/migrations/cabinet_labor_v1.sql');
    const bundle=JSON.parse(fs.readFileSync(path.join(root,'database/cabinet-labor/generated/cabinet-labor-bundle.json'),'utf8'));
    const literal=value=>`convert_from(decode('${Buffer.from(JSON.stringify(value)).toString('hex')}','hex'),'UTF8')::jsonb`;
    sql(`SELECT calc.stage_cabinet_labor_catalog_v1(${literal(bundle)}); SELECT calc.activate_cabinet_labor_catalog_v1('${bundle.data_version}'); UPDATE calc.cabinet_labor_catalog_version SET management_fee_rate=.13;`);
    for(let attempt=0;attempt<2;attempt++)file('database/migrations/enforce_management_fee_6_percent.sql');
    assert.equal(sql('SELECT management_fee_rate FROM calc.cabinet_labor_catalog_version WHERE status=\'ACTIVE\';'),'0.06');
    assert.equal(sql('SELECT formula_management_fee||\',\'||formula_total_cost FROM calc.dual_quote_result;'),'999,8888');
    const row=JSON.parse(sql('SELECT row_to_json(q) FROM calc.calculate_total_cost_by_spray_cost(1,826.52,49.60,332.54,720.88,80.65) q;'));
    assert.equal(row.management_fee,120.61); // no freight parameter in this base SQL function
    assert.equal(row.total_cost,2130.80);
    assert.equal(sql('SELECT management_fee FROM calc.calculate_total_cost(1,.75,0,0,0,0,0);'),'0.05');
    const old={...bundle,data_version:bundle.data_version.replace(/v\d+$/,'v99'),management_fee_rate:.13};
    assert.throws(()=>sql(`SELECT calc.stage_cabinet_labor_catalog_v1(${literal(old)});`),/Expected management fee rate 0.06/);
    assert.equal(sql("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='calc' AND p.proname IN ('calculate_total_cost','calculate_total_cost_by_spray_cost','stage_cabinet_labor_catalog_v1') AND pg_get_functiondef(p.oid) LIKE '%0.13%';"),'0');
  } finally {
    if(fs.existsSync(path.join(data,'postmaster.pid')))run('pg_ctl.exe',['-D',data,'-w','stop','-m','fast']);
    const resolved=fs.realpathSync(folder),parent=fs.realpathSync(path.join(root,'.codex-tmp'));
    if(path.dirname(resolved)!==parent||!path.basename(resolved).startsWith('management-fee-pg-'))
      throw new Error('Unexpected management regression cleanup path');
    fs.rmSync(resolved,{recursive:true,force:true});
  }
});
