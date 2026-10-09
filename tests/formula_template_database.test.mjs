import assert from 'node:assert/strict';
import test from 'node:test';
import {execFileSync} from 'node:child_process';
import {formulaTemplateSql} from '../api/formula_template_query.mjs';

const db = `template_cache_test_${Date.now()}`;
const psql = 'G:/PostgreSQL/18/bin/psql.exe';
const sql = (text, database = db) => execFileSync(psql, ['-X','-w','-h','127.0.0.1','-p','55439',
  '-U','attachment_test','-d',database,'-v','ON_ERROR_STOP=1','-A','-t','-q'], {input:text, encoding:'utf8'}).trim();
test('PostgreSQL template version changes on in-place formula/mapping edits and respects activation', () => {
  sql(`CREATE DATABASE ${db};`, 'postgres');
  try {
    sql(`CREATE SCHEMA calc;
      CREATE TABLE calc.template_formula_mapping(template_code text, source_sheet text, width_cell text,
        height_cell text, depth_cell text, option_cells jsonb, weight_output_cell text, area_output_cell text,
        weight_method text, area_unit text, is_active boolean);
      CREATE TABLE calc.cabinet_template(template_id integer, template_code text, weight_formula text, area_formula text, is_active boolean);
      CREATE TABLE calc.cabinet_part_rule(template_id integer, source_row_no integer, formula text);
      INSERT INTO calc.template_formula_mapping VALUES('JP_SINGLE','JP','B1','B2','B3','{}','W1','A1','sum','m2',true);
      INSERT INTO calc.cabinet_template VALUES(1,'JP_SINGLE','SUM(A1)','B1',true);
      INSERT INTO calc.cabinet_part_rule VALUES(1,1,'宽度*深度');`);
    const first = JSON.parse(sql(formulaTemplateSql('JP_SINGLE')));
    assert.match(first.template_version, /^[a-f0-9]{32}$/);
    assert.equal(first.template.rules[0].formula, '宽度*深度');
    const unchanged = JSON.parse(sql(formulaTemplateSql('JP_SINGLE', first.template_version)));
    assert.equal(unchanged.not_modified, true);
    assert.equal(unchanged.template, null);
    sql("UPDATE calc.cabinet_part_rule SET formula='宽度*高度';");
    const changed = JSON.parse(sql(formulaTemplateSql('JP_SINGLE', first.template_version)));
    assert.notEqual(changed.template_version, first.template_version);
    assert.equal(changed.template.rules[0].formula, '宽度*高度');
    sql("UPDATE calc.template_formula_mapping SET weight_method='new';");
    const mapping = JSON.parse(sql(formulaTemplateSql('JP_SINGLE', changed.template_version)));
    assert.notEqual(mapping.template_version, changed.template_version);
    sql('UPDATE calc.cabinet_template SET is_active=false;');
    assert.equal(sql(formulaTemplateSql('JP_SINGLE', mapping.template_version)), '');
  } finally { sql(`DROP DATABASE ${db};`, 'postgres'); }
});
