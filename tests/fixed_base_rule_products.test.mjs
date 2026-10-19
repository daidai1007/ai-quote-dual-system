// The database portion runs only against the disposable loopback test cluster.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import test from 'node:test';
import {calculateAttachment, selectRule} from '../api/attachment_cost.mjs';
import {createAttachmentService} from '../api/attachment_service.mjs';

const migrationUrl=new URL('../database/attachment-fixed-base-products-20261019/01-extend-r11-products.sql',import.meta.url);
const migration=fs.readFileSync(migrationUrl,'utf8');
const bundle=JSON.parse(fs.readFileSync(new URL('../database/attachment-v2/generated/attachment-bundle.json',import.meta.url)));
const added=['JQ_EXP','JE','JE_SINGLE','JE_DOUBLE','JS_WIDE_EXP','JP_WIDE_EXP'];
const retained=['JS','JS_SINGLE','JS_DOUBLE','JP','JP_SINGLE','JP_DOUBLE','JM'];
const originalRule=bundle.rules.find(row=>row.import_key==='R11');
const item=bundle.catalog.find(row=>row.import_key==='Q42');
const environment={product_code:'JP',width_mm:1000,height_mm:2200,depth_mm:600,
  material_code:'SECC',density_g_cm3:7.85,material_unit_price:5,spray_unit_price:26,
  coating_type:'橘纹',quote_date:'2026-10-19'};
const selection={quantity:1,manual_inputs:{底座高度:200}};

test('R11 scope migration is additive, active-version-only and leaves other rules alone',()=>{
  const targetValues=migration.match(/INSERT INTO r11_extension_target\(product_code\) VALUES([\s\S]*?);/)[1];
  assert.deepEqual([...targetValues.matchAll(/'([^']+)'/g)].map(match=>match[1]),added);
  assert.match(migration,/v\.status='ACTIVE' AND r\.import_key='R11'/);
  assert.match(migration,/pg_advisory_xact_lock/);
  assert.match(migration,/r\.method='CALCULATED'/);
  assert.match(migration,/ON CONFLICT \(rule_id,product_code\) DO NOTHING/);
  assert.doesNotMatch(migration,/\b(?:UPDATE|DELETE|ALTER|TRUNCATE)\b/i);
});

test('all added and retained products use the unchanged R11 formula, including materials and quantities',()=>{
  const rule={...originalRule,products:[...retained,...added]};
  for(const material of [
    {material_code:'SECC',density_g_cm3:7.85,material_unit_price:5},
    {material_code:'SUS304',density_g_cm3:7.93,material_unit_price:16},
    {material_code:'SUS316',density_g_cm3:7.98,material_unit_price:32.4},
  ]) for(const dims of [
    {width_mm:1000,depth_mm:600,base:200},
    {width_mm:1450,depth_mm:550,base:150},
  ]) for(const quantity of [1,2]) {
    const env={...environment,...material,...dims};
    const chosen={quantity,manual_inputs:{底座高度:dims.base}};
    const expected=calculateAttachment(chosen,item,[originalRule],env);
    assert.equal(expected.status,'CALCULATED');
    assert.ok(expected.formula_amount>0);
    const weight=(dims.width_mm-3+dims.depth_mm-53.3)*(dims.base+93.4)*2.5*env.density_g_cm3*0.000001*2;
    assert.ok(Math.abs(expected.weight_kg-weight)<1e-9);
    for(const product_code of [...retained,...added]) {
      const actual=calculateAttachment(chosen,item,[rule],{...env,product_code,height_mm:3100});
      assert.equal(actual.status,'CALCULATED',product_code);
      for(const field of ['formula_unit_cost','formula_amount','weight_kg','material_cost','spray_cost','labor_cost','quick_amount']) {
        assert.equal(actual[field],expected[field],`${product_code}: ${field}`);
      }
    }
  }
  for(const product of ['JA','JA_SINGLE','JK','JC_EXP','OP_TABLE_EXP','UNKNOWN']) assert.equal(selectRule([rule],product,'SECC'),null);
  assert.equal(calculateAttachment({quantity:1},item,[rule],{...environment,product_code:'JQ_EXP'}).status,'ERROR');
  const noSpray=calculateAttachment(selection,item,[rule],{...environment,product_code:'JE_SINGLE',coating_type:'不喷塑',spray_unit_price:null});
  assert.equal(noSpray.status,'CALCULATED');
  assert.equal(noSpray.spray_cost,0);
});

test('real PostgreSQL: migrate, re-run, resolve/catalogue/cost consistency and rollback guards',{
  skip:!process.env.ATTACHMENT_TEST_PSQL,
},async()=>{
  const psql=process.env.ATTACHMENT_TEST_PSQL;
  const db=`r11_products_test_${process.pid}_${Date.now()}`;
  const args=['-X','-w','-h','127.0.0.1','-p','55439','-U','attachment_test','-v','ON_ERROR_STOP=1','-A','-t','-q'];
  const sql=(text,database=db)=>execFileSync(psql,[...args,'-d',database],{input:text,encoding:'utf8',stdio:['pipe','pipe','pipe']}).trim();
  const file=relative=>sql(fs.readFileSync(new URL(`../${relative}`,import.meta.url),'utf8'));
  sql(`CREATE DATABASE ${db};`,'postgres');
  try {
    for(const relative of ['tests/fixtures/attachment_online_schema_20260911.sql',
      'database/attachment-v2/web/01-prepare.sql']) file(relative);
    const payload=Buffer.from(JSON.stringify(bundle)).toString('hex');
    sql(`SELECT calc.stage_attachment_catalog_v2(convert_from(decode('${payload}','hex'),'UTF8')::jsonb);`);
    sql(`BEGIN; SET LOCAL calc.attachment_v2_api_ready='on'; SELECT calc.switch_attachment_catalog_v2('${bundle.data_version}'); COMMIT;`);
    file('database/attachment-fixed-base-jm-20261015/01-add-jm-to-r11.sql');
    // A second inactive catalogue/R11 must remain unchanged.
    sql(`INSERT INTO calc.attachment_catalog_version(data_version,source_sha256,status,source_file,audit_report)
      VALUES('r11-inactive',repeat('0',64),'STAGED','local-test','{}');
      INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,category_level2,item_name,
        method,formulas,source_file,source_sheet,source_row_no,raw_values)
      SELECT 'r11-inactive',import_key,category_level1,category_level2,item_name,
        method,formulas,source_file,source_sheet,source_row_no,raw_values
      FROM calc.attachment_cost_rule WHERE import_key='R11' AND data_version='${bundle.data_version}';
      INSERT INTO calc.attachment_cost_rule_product SELECT rule_id,'JS' FROM calc.attachment_cost_rule WHERE data_version='r11-inactive';`);
    const before={};
    const tables=sql("SELECT tablename FROM pg_tables WHERE schemaname='calc' AND tablename<>'attachment_cost_rule_product' ORDER BY tablename;").split('\n');
    const snapshot=table=>sql(`SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') FROM calc.${table} t;`);
    for(const table of tables) before[table]=snapshot(table);
    const links=()=>JSON.parse(sql('SELECT jsonb_agg(to_jsonb(p) ORDER BY rule_id,product_code) FROM calc.attachment_cost_rule_product p;'));
    const originalLinks=links();
    file('database/attachment-fixed-base-products-20261019/00-readonly-check.sql');
    sql(migration);
    const afterFirst=links();
    assert.equal(afterFirst.length,originalLinks.length+added.length);
    sql(migration);
    assert.deepEqual(links(),afterFirst,'repeat must not duplicate links');
    for(const table of tables) assert.equal(snapshot(table),before[table],`${table} must be unchanged`);
    for(const row of originalLinks) assert.ok(afterFirst.some(link=>link.rule_id===row.rule_id&&link.product_code===row.product_code));
    const activeRule=JSON.parse(sql(`SELECT to_jsonb(r)||jsonb_build_object('products',
      (SELECT jsonb_agg(product_code ORDER BY product_code) FROM calc.attachment_cost_rule_product p WHERE p.rule_id=r.rule_id))
      FROM calc.attachment_cost_rule r WHERE r.import_key='R11' AND r.data_version='${bundle.data_version}';`));
    assert.deepEqual(activeRule.products,[...retained,...added].sort());
    const service=createAttachmentService({runPsql:async text=>sql(text),env:{}});
    const catalogue=await service.catalog();
    const base=catalogue.items.find(row=>row.source_row_no===42);
    const oldCost=calculateAttachment(selection,base,base.rules,environment);
    assert.equal(oldCost.status,'CALCULATED');
    for(const product_code of [...retained,...added]) {
      assert.equal(Number(sql(`SELECT calc.resolve_attachment_cost_rule(${base.attachment_price_id},'${product_code}','SECC');`)),activeRule.rule_id);
      const cost=calculateAttachment(selection,base,base.rules,{...environment,product_code});
      assert.equal(cost.status,'CALCULATED',product_code);
      assert.equal(cost.formula_amount,oldCost.formula_amount,product_code);
      assert.deepEqual(cost.formulas,originalRule.formulas);
    }
    for(const product of ['JA_SINGLE','JK','JC_EXP','OP_TABLE_EXP']) {
      assert.equal(sql(`SELECT calc.resolve_attachment_cost_rule(${base.attachment_price_id},'${product}','SECC');`),'');
    }
    file('database/attachment-fixed-base-products-20261019/00-readonly-check.sql');
    const linksBeforeFailure=links();
    sql(`UPDATE calc.attachment_cost_rule SET item_name='not-fixed-base' WHERE rule_id=${activeRule.rule_id};`);
    assert.throws(()=>sql(migration),/R11 不是预期的固定底座公式规则/);
    assert.deepEqual(links(),linksBeforeFailure);
    sql(`UPDATE calc.attachment_cost_rule SET item_name='固定底座',import_key='R11_MISSING' WHERE rule_id=${activeRule.rule_id};`);
    assert.throws(()=>sql(migration),/当前活动目录缺少唯一固定底座公式规则 R11/);
    assert.deepEqual(links(),linksBeforeFailure);
    sql(`UPDATE calc.attachment_catalog_version SET status='RETIRED' WHERE status='ACTIVE';`);
    assert.throws(()=>sql(migration),/必须且只能有一个活动附件目录版本/);
    assert.deepEqual(links(),linksBeforeFailure);
  } finally {
    sql(`DROP DATABASE ${db};`,'postgres');
  }
});
