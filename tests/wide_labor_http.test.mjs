// Real loopback API + disposable PostgreSQL; no application/production settings.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import {spawn} from 'node:child_process';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {startLocalPostgres} from './helpers/local_postgres.mjs';
import {installLocalNameScope,localApiSession} from './helpers/local_api_session.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));

test('all experience matchers use width/perimeter/area; migration rolls back; JS WIDE calculates through real HTTP',
  {timeout:180000},async()=>{
  const pg=await startLocalPostgres();let child;
  try{
    const file=async relative=>pg.query(await fs.readFile(path.join(root,relative),'utf8'));
    for(const f of ['tests/fixtures/attachment_online_schema_20260911.sql',
      'database/attachment-v2/web/01-prepare.sql','database/attachment-v2/web/02-stage.sql',
      'tests/fixtures/attachment_api_base_stub.sql'])await file(f);
    installLocalNameScope(pg.query);
    for(const f of ['cabinet_material_v2.sql','cabinet_spray_v2.sql','cabinet_auxiliary_v3.sql','cabinet_labor_v1.sql'])
      await file('database/migrations/'+f);
    for(const category of ['cabinet-material','cabinet-spray','cabinet-auxiliary','cabinet-labor']){
      await file('database/'+category+'/web/02-stage.sql');
      await file('database/'+category+'/web/04-activate.sql');
    }
    // Install the real automatic quick-price matcher over the synthetic base
    // schema; keep product/material/date restrictions and scaling untouched.
    pg.query(`DROP FUNCTION calc.match_quick_quote(text,text,text,numeric,numeric,numeric,date);
      ALTER TABLE calc.quick_quote_experience
        ADD COLUMN min_width_mm numeric,ADD COLUMN max_width_mm numeric,
        ADD COLUMN min_height_mm numeric,ADD COLUMN max_height_mm numeric,
        ADD COLUMN min_depth_mm numeric,ADD COLUMN max_depth_mm numeric,
        ADD COLUMN quick_material_cost numeric DEFAULT 0,ADD COLUMN quick_auxiliary_cost numeric DEFAULT 0,
        ADD COLUMN quick_labor_cost numeric DEFAULT 0,ADD COLUMN quick_attachment_fee numeric DEFAULT 0,
        ADD COLUMN quick_spray_cost numeric DEFAULT 0,ADD COLUMN quick_management_fee numeric DEFAULT 0,
        ADD COLUMN quick_total_cost numeric DEFAULT 200,ADD COLUMN effective_from date DEFAULT DATE '2026-01-01',
        ADD COLUMN effective_to date,ADD COLUMN is_active boolean DEFAULT true;
      INSERT INTO calc.quick_quote_experience(quick_rule_id,product_code,model_code,material_code,
        reference_width_mm,reference_height_mm,reference_depth_mm,quick_base_price,quick_total_cost)
      VALUES(2,'JS_WIDE_EXP','','SECC',1300,1800,600,200,200),
        (3,'JE_SINGLE','nearer-3d','SECC',600,1900,100,100,100),
        (4,'JE_SINGLE','nearer-area','SECC',600,1000,1000,200,200),
        (5,'JE_SINGLE','wrong-width','SECC',601,1600,399,9999,9999);
      CREATE TABLE calc.labor_experience_rule(labor_rule_id bigint,rule_scope text,product_code varchar,
        template_code varchar,model_code varchar,material_code varchar,width_mm numeric,height_mm numeric,
        depth_mm numeric,labor_cost numeric,is_active boolean);
      INSERT INTO calc.labor_experience_rule VALUES
        (1,'experience_product','JS_WIDE_EXP',NULL,'A','SECC',600,1900,100,100,true),
        (2,'experience_product','JS_WIDE_EXP',NULL,'B','SECC',600,1000,1000,200,true);`);
    const extract=(text,name)=>{
      const start=text.indexOf('CREATE OR REPLACE FUNCTION calc.'+name+'(');
      assert.ok(start>=0,name);
      const end=text.indexOf('$function$;',start);assert.ok(end>start,name);
      return text.slice(start,end+'$function$;'.length);
    };
    const legacy=await fs.readFile(path.join(root,'database/migrations/migrate_experience_formula_dimension_matching.sql'),'utf8');
    pg.query(extract(legacy,'normalize_experience_product_code'));
    pg.query(extract(legacy,'get_labor_cost_with_dimension_match'));
    pg.query(extract(await fs.readFile(path.join(root,'database/migrations/enforce_quick_quote_dimension_only.sql'),'utf8'),'match_quick_quote'));
    for(const [table,id,value] of [
      ['cabinet_material_fixed_rule','fixed_rule_id','material_weight_kg'],
      ['cabinet_spray_fixed_rule','fixed_rule_id','spray_cost'],
      ['cabinet_auxiliary_fixed_rule','rule_id','auxiliary_cost'],
    ]){
      const template=JSON.parse(pg.query(`SELECT to_jsonb(r)::text FROM calc.${table} r WHERE product_code='JS_WIDE_EXP' LIMIT 1;`));
      for(const [offset,height,depth,price] of [[1,1900,100,100],[2,1000,1000,200]]){
        const next=Number(pg.query(`SELECT nextval(pg_get_serial_sequence('calc.${table}','${id}'));`));
        const row={...template,[id]:next,model_code:'SYNTHETIC-'+offset,width_mm:600,height_mm:height,depth_mm:depth,
          [value]:price,source_row_no:9500+offset,source_sheet:'SYNTHETIC',import_key:'SYNTHETIC-'+offset};
        pg.query(`INSERT INTO calc.${table} OVERRIDING SYSTEM VALUE SELECT * FROM jsonb_populate_record(NULL::calc.${table},
          '${JSON.stringify(row).replaceAll("'","''")}'::jsonb);`);
      }
    }
    const definitions=()=>JSON.parse(pg.query(`SELECT jsonb_object_agg(signature,pg_get_functiondef(to_regprocedure(signature)))::text
      FROM (VALUES
        ('calc.match_quick_quote(character varying,character varying,character varying,numeric,numeric,numeric,date)'),
        ('calc.get_cabinet_material_fixed_weight(character varying,character varying,character varying,numeric,numeric,numeric)'),
        ('calc.get_cabinet_spray_fixed_cost(character varying,character varying,character varying,numeric,numeric,numeric)'),
        ('calc.get_auxiliary_cost(character varying,character varying,character varying,character varying,integer,integer,integer)'),
        ('calc.get_labor_cost_with_dimension_match(character varying,character varying,character varying,numeric,numeric,numeric)'),
        ('calc.get_experience_material_weight_by_dimension(character varying,character varying,numeric,numeric,numeric)'),
        ('calc.get_direct_spray_cost(character varying,character varying,numeric,numeric,numeric)')
      ) AS functions(signature);`));
    const originals=definitions();
    const migration=await fs.readFile(path.join(root,'database/migrations/enforce_experience_width_perimeter_area.sql'),'utf8');
    const rankIdentity='calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)';
    const rankDeclaration='calc.experience_dimension_rank(reference_width numeric,reference_height numeric,reference_depth numeric,target_width numeric,target_height numeric,target_depth numeric)';
    pg.query(`CREATE FUNCTION ${rankDeclaration} RETURNS numeric[] LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
      AS $$ SELECT ARRAY[999::numeric] $$;`);
    const unknownRank=pg.query(`SELECT pg_get_functiondef('${rankIdentity}'::regprocedure);`);
    assert.throws(()=>pg.query(migration),/Unexpected experience rank helper/);
    assert.equal(pg.query(`SELECT pg_get_functiondef('${rankIdentity}'::regprocedure);`),unknownRank);
    assert.equal(pg.query("SELECT to_regclass('calc.experience_dimension_match_backup') IS NULL;"),'t');
    pg.query('DROP FUNCTION '+rankIdentity+';');
    await file('database/migrations/enforce_experience_width_perimeter_area.sql');
    await file('database/migrations/enforce_experience_width_perimeter_area.sql'); // Idempotent.
    const knownRank=pg.query(`SELECT pg_get_functiondef('${rankIdentity}'::regprocedure);`);
    const installedDefinitions=definitions();
    pg.query(`CREATE OR REPLACE FUNCTION ${rankDeclaration} RETURNS numeric[] LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
      AS $$ SELECT ARRAY[999::numeric] $$;`);
    assert.throws(()=>pg.query(migration),/Unexpected experience rank helper/);
    await assert.rejects(()=>file('database/experience-dimension-match-20261028/03-rollback.sql'),/Rank helper missing or changed/);
    assert.deepEqual(definitions(),installedDefinitions,'unknown helper must stop before restoring any matcher');
    pg.query(knownRank);
    const quickIdentity='calc.match_quick_quote(character varying,character varying,character varying,numeric,numeric,numeric,date)';
    const changedQuick=installedDefinitions[quickIdentity].replace('AS $function$','AS $function$\n-- synthetic later repair\n');
    assert.notEqual(changedQuick,installedDefinitions[quickIdentity]);pg.query(changedQuick);
    assert.throws(()=>pg.query(migration),/Matcher changed after this migration/);
    await assert.rejects(()=>file('database/experience-dimension-match-20261028/03-rollback.sql'),/Matcher has newer changes/);
    pg.query(installedDefinitions[quickIdentity]);assert.deepEqual(definitions(),installedDefinitions);
    const selected=JSON.parse(pg.query(`SELECT jsonb_build_object(
      'material',calc.get_cabinet_material_fixed_weight('JS_WIDE_EXP','','SECC',600,1600,400),
      'spray',calc.get_cabinet_spray_fixed_cost('JS_WIDE_EXP','','SECC',600,1600,400),
      'auxiliary',calc.get_auxiliary_cost('JS_WIDE_EXP','DEFAULT','','SECC',600,1600,400),
      'labor',(SELECT labor_cost FROM calc.get_labor_cost_with_dimension_match('JS_WIDE_EXP',NULL,'SECC',600,1600,400)),
      'quick',(SELECT quick_total_cost FROM calc.match_quick_quote('JE_SINGLE','ignored','SECC',600,1600,400,DATE '2026-10-28'))
    )::text;`));
    assert.deepEqual(selected,{material:200,spray:200,auxiliary:200,labor:200,quick:200});
    assert.ok((await file('database/experience-dimension-match-20261028/02-readonly-verify.sql')).endsWith('t|t'));
    await file('database/experience-dimension-match-20261028/03-rollback.sql');
    assert.deepEqual(definitions(),originals,'all function definitions must be restored exactly');
    assert.equal(Number(pg.query("SELECT quick_total_cost FROM calc.match_quick_quote('JE_SINGLE','ignored','SECC',600,1600,400,DATE '2026-10-28');")),100);
    // Older installations keep their own material/spray implementations rather
    // than V2 delegates. Exercise both actual historical bodies as well.
    pg.query(`CREATE TABLE calc.experience_product(experience_product_id bigint,product_code varchar);
      CREATE TABLE calc.experience_product_model(model_id bigint,experience_product_id bigint,material_code varchar,
        width_mm numeric,height_mm numeric,depth_mm numeric,material_weight_kg numeric,base_density_g_cm3 numeric,is_active boolean);
      CREATE TABLE calc.experience_spray_price(experience_spray_price_id bigint,product_code varchar,material_code varchar,
        width_mm numeric,height_mm numeric,depth_mm numeric,direct_spray_cost numeric,updated_at timestamptz);
      INSERT INTO calc.experience_product VALUES(1,'JS_WIDE_EXP');
      INSERT INTO calc.experience_product_model VALUES
        (1,1,'SECC',600,1900,100,100,7.85,true),(2,1,'SECC',600,1000,1000,200,7.85,true);
      INSERT INTO calc.experience_spray_price VALUES
        (1,'JS_WIDE_EXP','SECC',600,1900,100,100,current_timestamp),
        (2,'JS_WIDE_EXP','SECC',600,1000,1000,200,current_timestamp);`);
    pg.query(extract(legacy,'get_experience_material_weight_by_dimension'));
    pg.query(extract(legacy,'get_direct_spray_cost'));
    const legacyOriginals=definitions();
    await file('database/migrations/enforce_experience_width_perimeter_area.sql');
    assert.equal(pg.query("SELECT count(*) FROM calc.experience_dimension_match_backup;"),'7');
    assert.equal(pg.query("SELECT calc.get_experience_material_weight_by_dimension('JS_WIDE_EXP','SECC',600,1600,400);"),'200.000000');
    assert.equal(pg.query("SELECT calc.get_direct_spray_cost('JS_WIDE_EXP','SECC',600,1600,400);"),'200.000000');
    await file('database/experience-dimension-match-20261028/03-rollback.sql');
    assert.deepEqual(definitions(),legacyOriginals,'legacy bodies must also be restored exactly');
    for(const signature of [
      'calc.get_experience_material_weight_by_dimension(character varying,character varying,numeric,numeric,numeric)',
      'calc.get_direct_spray_cost(character varying,character varying,numeric,numeric,numeric)',
    ])pg.query(originals[signature]);
    assert.deepEqual(definitions(),originals);
    const laborIdentity='calc.get_labor_cost_with_dimension_match(character varying,character varying,character varying,numeric,numeric,numeric)';
    pg.query('DROP FUNCTION '+laborIdentity+';');
    assert.throws(()=>pg.query(migration),/Required experience matcher missing/);
    assert.equal(pg.query("SELECT count(*) FROM calc.experience_dimension_match_backup;"),'0','failed migration must leave no partial changes');
    assert.equal(pg.query("SELECT to_regprocedure('calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)') IS NULL;"),'t');
    pg.query(originals[laborIdentity]);
    assert.deepEqual(definitions(),originals);
    await file('database/migrations/enforce_experience_width_perimeter_area.sql');
    const version=pg.query("SELECT data_version FROM calc.attachment_catalog_version WHERE status='STAGED';");
    assert.match(version,/^xlsx-[a-f0-9]{16}-r[0-9]+$/);
    pg.query(`BEGIN;SET LOCAL calc.attachment_v2_api_ready='on';SELECT calc.switch_attachment_catalog_v2('${version}');COMMIT;`);
    const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));
    const port=listener.address().port;await new Promise(r=>listener.close(r));
    const environment={...process.env,AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),
      AI_QUOTE_API_KEY:'local-regression-only',PSQL_PATH:pg.connection.psql,
      AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:String(pg.connection.port),
      AI_QUOTE_DB_USER:pg.connection.user,AI_QUOTE_DB_NAME:pg.connection.database,PGSSLMODE:'disable'};
    for(const key of ['DATABASE_URL','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD',
      'PGPASSFILE','PGSERVICE','PGSERVICEFILE','PGOPTIONS','RENDER','AI_QUOTE_PRINCIPALS_JSON'])delete environment[key];
    const logs=[];
    child=spawn(process.execPath,['api/server.mjs'],{cwd:root,env:environment,windowsHide:true,stdio:['ignore','pipe','pipe']});
    child.stdout.on('data',data=>logs.push(String(data)));child.stderr.on('data',data=>logs.push(String(data)));
    const base='http://127.0.0.1:'+port;let ready=false;
    for(let i=0;i<100;i++){
      if(child.exitCode!==null)throw Error('Local API exited');
      try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{}
      await new Promise(r=>setTimeout(r,100));
    }
    assert.ok(ready,'local API startup timeout');
    const api=await localApiSession(base);
    const input={quote_id:'LOCAL-WIDE-1350',product_code:'JS_WIDE_EXP',model_code:'',material_code:'SECC',
      width_mm:1350,height_mm:1250,depth_mm:400,quote_date:'2026-10-28',coating_type:'橘纹',
      single_door_count:1,double_door_count:0,waste_factor:1.2,cabinet_body_thickness_mm:1.5,
      material_unit_price_override:4.2,galvanized_sheet_unit_price_override:4.55,carbon_steel_unit_price_override:4.2,
      attachment_contract:2,attachments:[]};
    const response=await api.fetch('/api/quotes/calculate-dual',{method:'POST',
      headers:{'Content-Type':'application/json',Accept:'application/x-ndjson'},body:JSON.stringify(input)});
    const text=await response.text();assert.equal(response.status,200,text);
    const events=text.trim().split('\n').map(JSON.parse);
    assert.equal(events.at(-1).type,'result',JSON.stringify(events.at(-1)));
    const result=events.at(-1).result;
    assert.equal(result.formula_cost.labor_cost,316.22);
    assert.equal(result.formula_cost.labor_reference_model_code,'JS131860');
    assert.equal(result.formula_cost.labor_dimension_distance,345000);
    assert.equal(result.formula_cost.labor_perimeter_difference,700);
    assert.equal(result.quick_quote.base_price,162.162162); // Existing 200 * 3000/3700 scaling.
    assert.equal(pg.query('SELECT count(*) FROM calc.local_base_probe;'),'0','temporary base writes must roll back');
    const saved=JSON.parse(pg.query(`SELECT (environment_snapshot->'quote_result')::text FROM calc.attachment_quote_line WHERE quote_line_id='${result.quote_line_id}';`));
    assert.equal(saved.formula_cost.labor_cost,316.22);
    assert.equal(saved.formula_cost.labor_reference_model_code,'JS131860');
    const item={...input,name:'合成超宽柜',specification:'1350*400*(1250+200)',quantity:1,
      quote_line_id:result.quote_line_id,formula:result.formula_cost,formula_base:result.formula_cost,
      quick:result.quick_quote,attachments:result.attachments,labor_multiplier:1,freight_fee:0};
    const checked=await api.fetch('/api/quotes/preview-check',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({quote_id:'LOCAL-PREVIEW',items:[item]})});
    const body=await checked.json();assert.equal(checked.status,200,JSON.stringify(body));assert.equal(body.valid,true);
    assert.equal(body.persisted,false);
    // Current user screenshot: cabinet body 1800, separate base 200. Keep the
    // earlier 1250 case as an independent regression rather than changing it.
    const input1800={...input,quote_id:'LOCAL-WIDE-1350-H1800',height_mm:1800};
    const response1800=await api.fetch('/api/quotes/calculate-dual',{method:'POST',
      headers:{'Content-Type':'application/json',Accept:'application/x-ndjson'},body:JSON.stringify(input1800)});
    const text1800=await response1800.text();assert.equal(response1800.status,200,text1800);
    const events1800=text1800.trim().split('\n').map(JSON.parse);
    assert.equal(events1800.at(-1).type,'result',JSON.stringify(events1800.at(-1)));
    const result1800=events1800.at(-1).result;
    assert.equal(result1800.formula_cost.labor_cost,374.19); // Original 390 * 3550/3700, rounded to cents.
    assert.equal(result1800.formula_cost.labor_reference_model_code,'JS131860');
    assert.equal(result1800.formula_cost.labor_dimension_distance,42500);
    assert.equal(result1800.formula_cost.labor_perimeter_difference,150);
    const saved1800=JSON.parse(pg.query(`SELECT (environment_snapshot->'quote_result')::text FROM calc.attachment_quote_line WHERE quote_line_id='${result1800.quote_line_id}';`));
    assert.equal(saved1800.formula_cost.labor_cost,374.19);
    if(process.env.AI_QUOTE_WIDE_CALCULATION_FIXTURE){
      await fs.writeFile(process.env.AI_QUOTE_WIDE_CALCULATION_FIXTURE,JSON.stringify({input,result,height1800:{input:input1800,result:result1800}},null,2),'utf8');
    }
  }finally{
    if(child&&child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}
    await pg.close();
  }
});
