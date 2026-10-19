// Own a disposable loopback PostgreSQL cluster. Never read client credentials
// or point this suite at a production, backup or cloud rehearsal branch.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {createQuoteSchemeService} from '../api/quote_scheme_service.mjs';
import {startLocalPostgres} from './helpers/local_postgres.mjs';

const literal=value=>value==null?'NULL':`'${String(value).replaceAll("'","''")}'`;
const owner={userId:'local-owner',displayName:'测试人员',departmentId:'local-dept',role:'USER'};
const other={userId:'local-other',displayName:'其他人员',departmentId:'other-dept',role:'USER'};
const admin={userId:'local-admin',displayName:'测试管理员',departmentId:null,role:'ADMIN'};
const snapshot={company:'本机测试公司',draft_items:[{product_code:'JE_SINGLE',quantity:2,quoted_total:120}],
  scheme_summary:{company:'本机测试公司',product_summary:'JE',quoted_amount:120}};

test('quote-scheme transitions execute real SQL and retain all protection rules', {timeout:180000}, async t=>{
  const pg=await startLocalPostgres();
  try {
    pg.query('CREATE SCHEMA calc;');
    pg.query(await readFile(new URL('../database/migrations/quote_scheme_center_v1.sql',import.meta.url),'utf8'));
    const service=createQuoteSchemeService({runPsql:async sql=>pg.query(sql),
      sqlUnicodeText:literal,sqlNumber:value=>String(Number(value))});
    const row=no=>JSON.parse(pg.query(`SELECT row_to_json(s) FROM calc.quote_scheme s WHERE scheme_no=${literal(no)};`));
    const auditCount=no=>Number(pg.query(`SELECT count(*) FROM calc.quote_scheme_audit a JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${literal(no)};`));
    const lastAudit=no=>JSON.parse(pg.query(`SELECT row_to_json(a) FROM calc.quote_scheme_audit a JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${literal(no)} ORDER BY a.audit_id DESC LIMIT 1;`));
    const frozen=no=>pg.query(`SELECT snapshot_payload::text FROM calc.quote_scheme_snapshot q JOIN calc.quote_scheme s USING(scheme_id) WHERE s.scheme_no=${literal(no)};`);
    const create=async(status='DRAFT')=>{
      const created=await service.create(owner,{operator_name:'原创建人',snapshot:structuredClone(snapshot)});
      const no=created.scheme_no;
      if(status!=='DRAFT') await service.exportResult(owner,no,{operator_name:'原创建人',
        kind:'XLSX',succeeded:true,expected_version:1,snapshot:structuredClone(snapshot)});
      if(status==='REVISING') await service.revision(owner,no,2,'修订人员');
      if(status==='ARCHIVED') await service.transition(owner,no,'archive',2,'归档人员');
      return row(no);
    };
    const unchanged=(before,after)=>{
      for(const key of ['scheme_no','version_no','source_version_no','creator_user_id','creator_name_snapshot',
        'creator_name_entered','creator_identity_mode','creator_department_id','created_at',
        'company_name','product_summary','quoted_amount','has_successful_export','quoted_at']) {
        assert.deepEqual(after[key],before[key],key);
      }
    };

    await t.test('archive, restore, void write status, timestamps and exactly one audit each',async()=>{
      const initial=await create('QUOTED');
      let before=initial;
      const originalSnapshot=frozen(initial.scheme_no);
      for(const [action,status] of [['archive','ARCHIVED'],['restore','QUOTED'],['void','VOID']]) {
        const count=auditCount(initial.scheme_no);
        const result=await service.transition(owner,initial.scheme_no,action,before.lock_version,'当前操作人');
        const after=row(initial.scheme_no), audit=lastAudit(initial.scheme_no);
        assert.equal(result.changed,true);
        assert.equal(result.status,status);
        assert.equal(after.status,status);
        assert.equal(after.lock_version,before.lock_version+1);
        assert.equal(after.last_editor_user_id,owner.userId);
        assert.equal(after.last_editor_name_snapshot,'当前操作人');
        assert.equal(auditCount(initial.scheme_no),count+1);
        assert.equal(audit.action,action.toUpperCase());
        assert.equal(audit.from_status,before.status);
        assert.equal(audit.to_status,status);
        assert.equal(audit.actor_user_id,owner.userId);
        assert.equal(audit.actor_name_snapshot,'当前操作人');
        assert.equal(frozen(initial.scheme_no),originalSnapshot);
        if(action==='archive') assert.ok(after.archived_at);
        else assert.equal(after.archived_at,before.archived_at);
        if(action==='void') assert.ok(after.voided_at);
        else assert.equal(after.voided_at,before.voided_at);
        unchanged(before,after);
        before=after;
      }
    });

    for(const status of ['DRAFT','QUOTED','REVISING','ARCHIVED']) {
      await t.test(`void accepts ${status} and retains the quote snapshot`,async()=>{
        const before=await create(status), payload=frozen(before.scheme_no), count=auditCount(before.scheme_no);
        await service.transition(owner,before.scheme_no,'void',before.lock_version,'作废人员');
        const after=row(before.scheme_no);
        assert.equal(after.status,'VOID');
        assert.ok(after.voided_at);
        assert.equal(after.archived_at,before.archived_at);
        assert.equal(frozen(before.scheme_no),payload);
        assert.equal(auditCount(before.scheme_no),count+1);
        unchanged(before,after);
      });
    }

    await t.test('stale and repeated requests cannot change the row or add audit records',async()=>{
      const initial=await create('QUOTED');
      await service.transition(owner,initial.scheme_no,'archive',initial.lock_version,'操作人');
      const before=row(initial.scheme_no), count=auditCount(initial.scheme_no);
      await assert.rejects(()=>service.transition(owner,initial.scheme_no,'restore',initial.lock_version,'操作人'),e=>e.statusCode===409);
      await assert.rejects(()=>service.transition(owner,initial.scheme_no,'archive',before.lock_version,'操作人'),e=>e.statusCode===409);
      assert.deepEqual(row(initial.scheme_no),before);
      assert.equal(auditCount(initial.scheme_no),count);
    });

    await t.test('forbidden states and bad inputs remain rejected',async()=>{
      const draft=await create();
      const before=row(draft.scheme_no), count=auditCount(draft.scheme_no);
      for(const action of ['archive','restore']) {
        await assert.rejects(()=>service.transition(owner,draft.scheme_no,action,1,'操作人'),e=>e.statusCode===409);
      }
      for(const [action,version,name] of [['unknown',1,'操作人'],['void',0,'操作人'],['void',1,'']]) {
        await assert.rejects(()=>service.transition(owner,draft.scheme_no,action,version,name),e=>e.statusCode===400);
      }
      assert.deepEqual(row(draft.scheme_no),before);
      assert.equal(auditCount(draft.scheme_no),count);
      await service.transition(owner,draft.scheme_no,'void',1,'操作人');
      const voided=row(draft.scheme_no), voidCount=auditCount(draft.scheme_no);
      for(const action of ['archive','restore','void']) {
        await assert.rejects(()=>service.transition(owner,draft.scheme_no,action,voided.lock_version,'操作人'),e=>e.statusCode===409);
      }
      assert.deepEqual(row(draft.scheme_no),voided);
      assert.equal(auditCount(draft.scheme_no),voidCount);
    });

    await t.test('other users cannot transition a scheme; admin audit and creator protection remain intact',async()=>{
      for(const [status,action] of [['QUOTED','archive'],['ARCHIVED','restore'],['DRAFT','void']]) {
        const before=await create(status), count=auditCount(before.scheme_no);
        await assert.rejects(()=>service.transition(other,before.scheme_no,action,before.lock_version,'其他人员'),e=>e.statusCode===409);
        assert.deepEqual(row(before.scheme_no),before);
        assert.equal(auditCount(before.scheme_no),count);
        await service.transition(admin,before.scheme_no,action,before.lock_version,'管理员操作');
        const after=row(before.scheme_no);
        unchanged(before,after);
        assert.equal(after.last_editor_user_id,admin.userId);
        assert.equal(lastAudit(before.scheme_no).actor_user_id,admin.userId);
      }
    });
  } finally {
    await pg.close();
  }
});
