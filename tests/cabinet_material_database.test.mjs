import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync,spawn} from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import test, {after} from 'node:test';
import {fileURLToPath} from 'node:url';

import {applyCabinetMaterial,createCabinetMaterialService} from '../api/cabinet_material_service.mjs';
import {createCabinetSprayService} from '../api/cabinet_spray_service.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const psql=process.env.ATTACHMENT_TEST_PSQL||'G:/PostgreSQL/18/bin/psql.exe';
const dbHost=process.env.ATTACHMENT_TEST_DB_HOST||'127.0.0.1';
const db=`cabinet_material_test_${Date.now()}`;
const base=['-X','-w','-h',dbHost,'-p','55439','-U','attachment_test','-v','ON_ERROR_STOP=1','-A','-t','-q'];
const sql=(source,database=db)=>execFileSync(psql,[...base,'-d',database],{input:source,encoding:'utf8',stdio:['pipe','pipe','pipe']}).trim();
const runFile=(relative,database=db)=>sql(fs.readFileSync(path.join(root,relative),'utf8'),database);

test('versioned cabinet catalog stages, activates, calculates and saves an immutable snapshot',async()=>{
  sql(`CREATE DATABASE ${db};`,'postgres');
  sql(`CREATE SCHEMA calc;
    CREATE TABLE calc.material(material_code varchar PRIMARY KEY,density_g_cm3 numeric NOT NULL);
    INSERT INTO calc.material VALUES('SECC',7.85),('SUS304',7.93),('SUS316',7.98);
    CREATE FUNCTION calc.get_material_unit_price(varchar,date) RETURNS numeric LANGUAGE sql STABLE
      AS 'SELECT CASE WHEN $1=''SECC'' THEN 5 WHEN $1=''SUS304'' THEN 20 ELSE 30 END::numeric';
    CREATE FUNCTION calc.get_spray_unit_price(date,text) RETURNS numeric LANGUAGE sql STABLE
      AS 'SELECT CASE WHEN $2=''不喷塑'' THEN 0 ELSE 12 END::numeric';
    CREATE TABLE calc.experience_spray_price(experience_spray_price_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      product_code text,material_code text,width_mm numeric,height_mm numeric,depth_mm numeric,direct_spray_cost numeric,
      updated_at timestamptz DEFAULT current_timestamp);
    CREATE TABLE calc.dual_quote_result(
      quote_id varchar PRIMARY KEY,formula_material_cost numeric,formula_total_cost numeric,
      formula_auxiliary_cost numeric,formula_labor_cost numeric,formula_management_fee numeric,
      formula_product_area_m2 numeric,formula_spray_cost numeric,difference_cost numeric,
      updated_at timestamptz DEFAULT current_timestamp);
  `);
  runFile('database/migrations/cabinet_material_v2.sql');
  runFile('database/migrations/cabinet_spray_v2.sql');
  runFile('database/migrations/cabinet_auxiliary_v2.sql');
  runFile('database/migrations/cabinet_labor_v1.sql');
  const staged=runFile('database/cabinet-material/web/02-stage.sql');
  assert.match(staged,/cabinet-material-4f8bf726efa6568d-v2/);
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_material_rule;`),'241');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_material_fixed_rule;`),'46');
  assert.equal(sql(`SELECT count(DISTINCT family) FROM calc.cabinet_material_rule;`),'6');
  assert.equal(sql(`SELECT calc.activate_cabinet_material_catalog_v2('cabinet-material-4f8bf726efa6568d-v2');`),'cabinet-material-4f8bf726efa6568d-v2');
  const sprayStaged=runFile('database/cabinet-spray/web/02-stage.sql');
  assert.match(sprayStaged,/cabinet-spray-4b3d73c9cb7a6f26-v2/);
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_spray_rule;`),'202');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_spray_fixed_rule;`),'46');
  assert.equal(sql(`SELECT calc.activate_cabinet_spray_catalog_v2('cabinet-spray-4b3d73c9cb7a6f26-v2');`),'cabinet-spray-4b3d73c9cb7a6f26-v2');
  const sprayService=createCabinetSprayService({runPsql:async source=>sql(source)});
  const fixedSprayInput={product_code:'JQ_EXP',model_code:'JQ609648',material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480,
    quote_date:'2026-09-11',coating_type:'橘纹'};
  const fixedSpray=await sprayService.calculate(fixedSprayInput);
  assert.equal(fixedSpray.spray_cost,49.5);assert.equal(fixedSpray.match_method,'FIXED_EXACT');
  assert.equal((await sprayService.calculate({...fixedSprayInput,coating_type:'不喷塑'})).spray_cost,0);
  assert.equal(sql(`SELECT calc.get_product_spray_cost('JQ_EXP','JQ609648','SECC',600,960,480,1,12);`),'49.500000');
  assert.equal(sql(`SELECT calc.get_product_spray_cost('JQ_EXP','JQ609648','SECC',600,960,480,1,0);`),'0');
  const auxiliaryStaged=runFile('database/cabinet-auxiliary/web/02-stage.sql');
  assert.match(auxiliaryStaged,/cabinet-auxiliary-706c234a5de12a39-v2/);
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_auxiliary_line;`),'255');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_auxiliary_fixed_rule;`),'72');
  assert.equal(sql(`SELECT calc.activate_cabinet_auxiliary_catalog_v2('cabinet-auxiliary-706c234a5de12a39-v2');`),'cabinet-auxiliary-706c234a5de12a39-v2');
  const laborStaged=runFile('database/cabinet-labor/web/02-stage.sql');
  assert.match(laborStaged,/cabinet-labor-a3d12580527a3eb6-v1/);
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_labor_rule;`),'57');
  assert.equal(sql(`SELECT calc.activate_cabinet_labor_catalog_v1('cabinet-labor-a3d12580527a3eb6-v1');`),'cabinet-labor-a3d12580527a3eb6-v1');
  runFile('database/migrations/update_jm_labor_billable_weight.sql');
  assert.equal(sql(`SELECT data_version FROM calc.cabinet_labor_catalog_version WHERE status='ACTIVE';`),'cabinet-labor-01249192a2981dc7-v2');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_labor_rule WHERE data_version='cabinet-labor-01249192a2981dc7-v2';`),'58');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_labor_rule WHERE data_version='cabinet-labor-01249192a2981dc7-v2' AND product_code='JM' AND rule_kind='LINEAR_WEIGHT';`),'2');

  const service=createCabinetMaterialService({runPsql:async source=>sql(source)});
  const input={quote_id:'CABINET-1',product_code:'JS',material_code:'SUS304',width_mm:1000,height_mm:1800,
    depth_mm:600,single_door_count:1,double_door_count:0,cabinet_body_thickness_mm:1.5,
    waste_factor:1.3,quote_date:'2026-09-11',coating_type:'橘纹'};
  const material=await service.calculate(input);
  assert.equal(material.data_version,'cabinet-material-4f8bf726efa6568d-v2');
  assert.equal(material.waste_factor,1.3);
  assert.ok(material.net_material_weight_kg>0);
  assert.ok(Math.abs(material.corrected_material_weight_kg-material.net_material_weight_kg*1.3)<1e-7);
  assert.ok(material.part_details.some(row=>row.fixed_material_code==='SECC'&&row.material_code==='SECC'));
  assert.ok(material.part_details.some(row=>row.material_code==='SUS304'));

  sql(`INSERT INTO calc.dual_quote_result(quote_id,formula_material_cost,formula_total_cost) VALUES('CABINET-1',999,1200);`);
  const result=applyCabinetMaterial({formula_cost:{material_cost:999,total_cost:1200},quick_quote:{total_cost:1500}},material);
  await service.persist('CABINET-1',result,material);
  const saved=JSON.parse(sql(`SELECT jsonb_build_object('net',formula_net_material_weight_kg,'billable',formula_corrected_material_weight_kg,
    'factor',formula_waste_factor,'version',cabinet_material_version,'snapshot',cabinet_material_snapshot)::text
    FROM calc.dual_quote_result WHERE quote_id='CABINET-1';`));
  assert.equal(Number(saved.factor),1.3);
  assert.equal(saved.version,material.data_version);
  assert.equal(saved.snapshot.part_details.length,material.part_details.length);

  const defaulted=await service.calculate({...input,quote_id:'CABINET-2',waste_factor:undefined});
  assert.equal(defaulted.waste_factor,1.2);

  const experience=await service.calculate({quote_id:'CABINET-EXP',product_code:'JQ_EXP',model_code:'JQ609648',
    material_code:'SECC',width_mm:600,height_mm:960,depth_mm:480,waste_factor:1.8,quote_date:'2026-09-11'});
  assert.equal(experience.data_version,'cabinet-material-4f8bf726efa6568d-v2');
  assert.equal(experience.corrected_material_weight_kg,54);
  assert.equal(experience.material_cost,270);
  assert.equal(experience.waste_factor,1);
  assert.equal(experience.requested_waste_factor,1.8);
  assert.equal(experience.waste_factor_applied,false);
  assert.equal(experience.match_method,'FIXED_EXACT');
  assert.equal(sql(`SELECT calc.get_cabinet_material_fixed_weight('JQ_EXP','JQ609648','SECC',600,960,480);`),'54.000000');
  assert.equal(sql(`SELECT calc.get_corrected_material_weight_kg('JQ_EXP','JQ609648','SECC',600,960,480,NULL);`),'54.000000');

  sql(`CREATE TABLE calc.quick_quote_experience(quick_rule_id bigint,product_code text,model_code text,material_code text,
      reference_width_mm numeric,reference_height_mm numeric,reference_depth_mm numeric,quick_base_price numeric,
      source_file text,source_sheet text,source_row_no integer);
    INSERT INTO calc.quick_quote_experience VALUES(1,'JS','','SUS304',1000,1800,600,2000,'LOCAL','LOCAL',1);
    CREATE FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date)
      RETURNS TABLE(quick_rule_id bigint,quick_total_cost numeric,match_method text,dimension_distance numeric)
      LANGUAGE sql AS $$ SELECT 1::bigint,2000::numeric,'LOCAL'::text,0::numeric $$;
    CREATE FUNCTION calc.calculate_dual_quote(text,text,text,text,numeric,numeric,numeric,numeric,numeric,text,text,date)
      RETURNS TABLE(quote_id text,formula_material_cost numeric,formula_auxiliary_cost numeric,formula_labor_cost numeric,
       formula_attachment_fee numeric,formula_product_area_m2 numeric,formula_spray_cost numeric,formula_management_fee numeric,
       formula_total_cost numeric,quick_attachment_fee numeric,risk_flags jsonb)
      LANGUAGE plpgsql AS $$ BEGIN
        INSERT INTO calc.dual_quote_result(quote_id,formula_material_cost,formula_total_cost)
          VALUES($1,999,1200) ON CONFLICT ON CONSTRAINT dual_quote_result_pkey
          DO UPDATE SET formula_material_cost=999,formula_total_cost=1200;
        RETURN QUERY SELECT $1,999::numeric,5::numeric,10::numeric,0::numeric,2::numeric,5::numeric,1.3::numeric,1200::numeric,0::numeric,'[]'::jsonb;
      END $$;`);
  const reserve=net.createServer();await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));
  const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
  const child=spawn(process.execPath,[path.join(root,'api/server.mjs')],{cwd:root,windowsHide:true,env:{...process.env,
    DATABASE_URL:'',PGSERVICE:undefined,PGSERVICEFILE:undefined,PGPASSWORD:'',RENDER:'',AI_QUOTE_API_KEY:'',AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),PSQL_PATH:psql,
    AI_QUOTE_DB_HOST:dbHost,AI_QUOTE_DB_PORT:'55439',AI_QUOTE_DB_USER:'attachment_test',AI_QUOTE_DB_NAME:db}});
  try{
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('local API startup timeout')),10000);
      child.stdout.on('data',data=>{if(String(data).includes('listening')){clearTimeout(timer);resolve();}});
      child.once('error',reject);child.once('exit',code=>{clearTimeout(timer);reject(new Error(`API exited ${code}`));});});
    const response=await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...input,quote_id:'HTTP-CABINET',waste_factor:1.35})});
    const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));
    assert.equal(body.formula_cost.waste_factor,1.35);
    assert.ok(body.formula_cost.material_details.some(row=>row.material_code==='SECC'));
    assert.ok(body.formula_cost.material_details.some(row=>row.material_code==='SUS304'));
    assert.equal(body.formula_cost.cabinet_spray_version,'cabinet-spray-4b3d73c9cb7a6f26-v2');
    assert.equal(body.formula_cost.cabinet_auxiliary_version,'cabinet-auxiliary-706c234a5de12a39-v2');
    assert.equal(body.formula_cost.cabinet_labor_version,'cabinet-labor-01249192a2981dc7-v2');
    assert.ok(body.formula_cost.auxiliary_cost>0);
    assert.ok(body.formula_cost.labor_cost>0);
    assert.equal(body.formula_cost.management_fee,Math.round(body.formula_cost.labor_cost*.13*100)/100);
    assert.equal(body.quick_quote.base_price,2000);
    assert.equal(body.quick_quote.total_cost,2000);
    assert.ok(body.formula_cost.product_area_m2>0);
    assert.equal(body.formula_cost.spray_cost,Math.round(body.formula_cost.product_area_m2*12*100)/100);
    assert.equal(sql(`SELECT formula_waste_factor FROM calc.dual_quote_result WHERE quote_id='HTTP-CABINET';`),'1.35');
    assert.equal(sql(`SELECT cabinet_spray_version FROM calc.dual_quote_result WHERE quote_id='HTTP-CABINET';`),'cabinet-spray-4b3d73c9cb7a6f26-v2');
    assert.equal(sql(`SELECT cabinet_auxiliary_version FROM calc.dual_quote_result WHERE quote_id='HTTP-CABINET';`),'cabinet-auxiliary-706c234a5de12a39-v2');
    assert.equal(sql(`SELECT cabinet_labor_version FROM calc.dual_quote_result WHERE quote_id='HTTP-CABINET';`),'cabinet-labor-01249192a2981dc7-v2');

    const experienceResponse=await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`,{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({quote_id:'HTTP-EXPERIENCE',product_code:'JQ_EXP',model_code:'JQ609648-1',material_code:'SECC',
        width_mm:600,height_mm:960,depth_mm:480,waste_factor:1.8,quote_date:'2026-09-11',coating_type:'橘纹'})});
    const experienceBody=await experienceResponse.json();assert.equal(experienceResponse.status,200,JSON.stringify(experienceBody));
    assert.equal(experienceBody.formula_cost.net_material_weight_kg,54);
    assert.equal(experienceBody.formula_cost.corrected_material_weight_kg,54);
    assert.equal(experienceBody.formula_cost.material_cost,270);
    assert.equal(experienceBody.formula_cost.waste_factor,1);
    assert.equal(experienceBody.formula_cost.requested_waste_factor,1.8);
    assert.equal(experienceBody.formula_cost.waste_factor_applied,false);
    assert.equal(experienceBody.formula_cost.cabinet_material_method,'FIXED');
    assert.equal(sql(`SELECT formula_waste_factor FROM calc.dual_quote_result WHERE quote_id='HTTP-EXPERIENCE';`),'1');
  } finally {child.kill();await new Promise(resolve=>child.exitCode!==null?resolve():child.once('exit',resolve));}
  runFile('database/online-rollout-20260911/spray-cleanup/01-delete-legacy-spray.sql');
  assert.equal(sql(`SELECT to_regclass('calc.experience_spray_price') IS NULL;`),'t');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_spray_rule;`),'202');
  assert.equal(sql(`SELECT count(*) FROM calc.cabinet_spray_fixed_rule;`),'46');
});

after(()=>{
  try{sql(`SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}'; DROP DATABASE IF EXISTS ${db};`,'postgres');}
  catch{}
});
