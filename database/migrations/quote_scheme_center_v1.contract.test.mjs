import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const sql=await readFile(new URL('./quote_scheme_center_v1.sql',import.meta.url),'utf8');
test('migration owns numbering, immutable creator, snapshots and audit',()=>{
  for(const token of [
    'next_quote_scheme_number','BJ-','quote_scheme_creator_immutable','creator_name_entered',
    'creator_identity_mode','creator_department_id','quote_scheme_snapshot','quote_scheme_version',
    'source_version_no','quote_scheme_item','quote_scheme_share','quote_scheme_audit',
    'quote_scheme_export','quote_scheme_delete_guard','only an unused draft quote scheme can be deleted',
  ]) assert.ok(sql.includes(token),token);
  assert.match(sql,/DRAFT.+QUOTED.+REVISING.+ARCHIVED.+VOID/s);
  assert.match(sql,/creator_name_entered IS DISTINCT FROM OLD\.creator_name_entered/);
  assert.match(sql,/creator_department_id IS DISTINCT FROM OLD\.creator_department_id/);
  assert.match(sql,/OLD\.status <> 'DRAFT' OR OLD\.has_successful_export/);
  assert.doesNotMatch(sql,/DROP\s+TABLE\s+calc\.quote_scheme/i);
});
