import crypto from 'node:crypto';
import {isNamePrincipal,quoteScopeSql,sessionOperator,currentQuotePrincipal} from './quote_access_scope.mjs';
import {authError} from './name_login_service.mjs';
import {snapshotWithOrderNature, snapshotOrderNature, orderNatureSql, validateOrderNature} from '../quote_order_nature.mjs';
import {contractQuote} from './contract_quote.mjs';
import {displayVersion} from './quote_delivery_document.mjs';

const STATUSES = Object.freeze(['DRAFT', 'QUOTED', 'CONTRACT', 'REVISING', 'ARCHIVED', 'VOID']);
const ROLES = Object.freeze(['USER', 'DEPARTMENT_MANAGER', 'ADMIN']);
const TRANSITIONS = Object.freeze({
  DRAFT: new Set(['QUOTED', 'VOID']),
  QUOTED: new Set(['ARCHIVED', 'VOID']),
  CONTRACT: new Set(['ARCHIVED', 'VOID']),
  REVISING: new Set(['QUOTED', 'VOID']),
  ARCHIVED: new Set(['QUOTED', 'CONTRACT', 'VOID']),
  VOID: new Set(),
});

const apiKeyHash = (value) => crypto.createHash('sha256').update(String(value || ''), 'utf8').digest('hex');

const loadPrincipalMap = (text = process.env.AI_QUOTE_PRINCIPALS_JSON) => {
  if (!String(text || '').trim()) return new Map();
  let values;
  try { values = JSON.parse(text); } catch { throw new Error('AI_QUOTE_PRINCIPALS_JSON must be valid JSON'); }
  if (!Array.isArray(values)) throw new Error('AI_QUOTE_PRINCIPALS_JSON must be an array');
  const result = new Map();
  for (const [index, value] of values.entries()) {
    const hash = String(value?.api_key_sha256 || '').trim().toLowerCase();
    const userId = String(value?.user_id || '').trim();
    const name = String(value?.display_name || '').trim();
    const role = String(value?.role || 'USER').trim().toUpperCase();
    if (!/^[0-9a-f]{64}$/.test(hash) || !userId || !name || !ROLES.includes(role)) {
      throw new Error(`AI_QUOTE_PRINCIPALS_JSON[${index}] is invalid`);
    }
    if (result.has(hash)) throw new Error('AI_QUOTE_PRINCIPALS_JSON contains a duplicate key hash');
    result.set(hash, Object.freeze({
      userId, displayName: name,
      departmentId: String(value.department_id || '').trim() || null,
      role,
    }));
  }
  return result;
};

const resolvePrincipal = (req, principalMap) => {
  const key = String(req?.headers?.['x-ai-quote-key'] || '');
  const principal = principalMap.get(apiKeyHash(key));
  if (!principal) {
    const error = new Error('报价方案身份尚未配置，请联系管理员完成账号、部门和角色映射。');
    error.statusCode = 503;
    error.code = 'quote_scheme_identity_not_configured';
    throw error;
  }
  return principal;
};

const resolveQuoteSchemePrincipal = (req, principalMap, sharedApiKey = '') => {
  const principal=currentQuotePrincipal();
  if(!isNamePrincipal(principal))throw authError();
  return principal;
};

const assertTransition = (from, to) => {
  if (!STATUSES.includes(from) || !STATUSES.includes(to) || !TRANSITIONS[from].has(to)) {
    const error = new Error(`invalid quote scheme status transition: ${from} -> ${to}`);
    error.statusCode = 409;
    throw error;
  }
};

const canReadScheme = (principal, scheme) => isNamePrincipal(principal)
  ? principal.can_view_all_quotes===true || (scheme.effective_owner_user_id||scheme.creator_user_id)===principal.userId
  : principal.role === 'ADMIN'
  || String(scheme.creator_user_id) === principal.userId
  || Boolean(scheme.shared)
  || (principal.role === 'DEPARTMENT_MANAGER' && principal.departmentId
    && String(scheme.creator_department_id || '') === principal.departmentId);

const validSchemeNo = (value) => /^BJ-[0-9]{8}-[0-9]{6}$/.test(String(value || ''));
const positiveVersion = (value) => Number.isInteger(Number(value)) && Number(value) > 0;
const snapshotValue = (input) => {
  const value = input?.snapshot;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    const error = new Error('snapshot must be an object'); error.statusCode = 400; throw error;
  }
  return snapshotWithOrderNature(value);
};

const operatorNameValue = (input) => {
  const value = String(input?.operator_name || '').replace(/[\u0000-\u001f\u007f]/gu, '').trim().normalize('NFC');
  if (!value || value.length > 100) {
    const error = new Error('operator_name is required and must not exceed 100 characters');
    error.statusCode = 400;
    throw error;
  }
  return value;
};

const summaryFromSnapshot = (snapshot) => {
  const items = Array.isArray(snapshot.draft_items) ? snapshot.draft_items : [];
  const explicit = snapshot.scheme_summary && typeof snapshot.scheme_summary === 'object'
    ? snapshot.scheme_summary : null;
  const company = String(explicit?.company ?? snapshot.company ?? '').trim().slice(0, 500);
  const products = [];
  let amount = 0;
  for (const item of items) {
    const product = String(item?.product_name || item?.product_code || item?.name || '').trim();
    const specification = String(item?.specification || item?.model_code || '').trim();
    const label = [product, specification].filter(Boolean).join(' ');
    if (label && !products.includes(label)) products.push(label);
    const total = Number(item?.quoted_total ?? item?.quote_total ?? item?.total_quote ?? item?.quick_quote_total);
    if (Number.isFinite(total)) amount += total;
  }
  const explicitAmount = Number(explicit?.quoted_amount);
  const explicitProducts = String(explicit?.product_summary || '').trim();
  return {
    company,
    productSummary:(explicitProducts || products.slice(0, 3).join('；')).slice(0, 1000),
    amount:Number.isFinite(explicitAmount) ? explicitAmount : amount,
  };
};

const permissionSql = (principal, alias = 's') => {
  principal=currentQuotePrincipal()||principal;
  if(isNamePrincipal(principal))return quoteScopeSql(principal,alias);
  const uid = `convert_from(decode('${Buffer.from(principal.userId).toString('hex')}', 'hex'), 'UTF8')`;
  const dept = principal.departmentId
    ? `convert_from(decode('${Buffer.from(principal.departmentId).toString('hex')}', 'hex'), 'UTF8')`
    : 'NULL';
  if (principal.role === 'ADMIN') return 'TRUE';
  const own = `${alias}.creator_user_id = ${uid}`;
  const shared = `EXISTS (SELECT 1 FROM calc.quote_scheme_share sh WHERE sh.scheme_id=${alias}.scheme_id AND sh.grantee_user_id=${uid})`;
  const department = principal.role === 'DEPARTMENT_MANAGER' && principal.departmentId
    ? `${alias}.creator_department_id = ${dept}` : 'FALSE';
  return `(${own} OR ${shared} OR ${department})`;
};

const writePermissionSql = (principal, alias = 's') => {
  principal=currentQuotePrincipal()||principal;
  if(isNamePrincipal(principal))return quoteScopeSql(principal,alias,true);
  if (principal.role === 'ADMIN') return 'TRUE';
  const uid = `convert_from(decode('${Buffer.from(principal.userId).toString('hex')}', 'hex'), 'UTF8')`;
  const own = `${alias}.creator_user_id = ${uid}`;
  const department = principal.role === 'DEPARTMENT_MANAGER' && principal.departmentId
    ? `${alias}.creator_department_id = convert_from(decode('${Buffer.from(principal.departmentId).toString('hex')}', 'hex'), 'UTF8')`
    : 'FALSE';
  return `(${own} OR ${department})`;
};

const escapeLike = (value) => String(value || '').replaceAll('\\', '\\\\').replaceAll('%', '\\%').replaceAll('_', '\\_');

const createQuoteSchemeService = ({ runPsql, sqlUnicodeText, sqlNumber }) => {
  const query = async (sql) => {
    const output = await runPsql(sql);
    const line = String(output || '').split(/\r?\n/).map((v) => v.trim()).filter(Boolean).at(-1);
    return line ? JSON.parse(line) : null;
  };
  const principalValues = (p) => ({
    id: sqlUnicodeText(p.userId), name: sqlUnicodeText(p.displayName), dept: sqlUnicodeText(p.departmentId),
    identityMode: sqlUnicodeText(p.identityMode==='NAME_ONLY'?'SELF_REPORTED':p.identityMode || 'AUTHENTICATED'),
    auditMode: sqlUnicodeText(p.identityMode || 'AUTHENTICATED'),
  });
  const natureUnchanged = (snapshot, alias='s') => `NOT EXISTS (SELECT 1 FROM calc.quote_scheme_version nature_lock
    WHERE nature_lock.scheme_id=${alias}.scheme_id AND ${orderNatureSql('nature_lock.snapshot_payload')}<>'UNCLASSIFIED'
      AND ${orderNatureSql('nature_lock.snapshot_payload')}<>${sqlUnicodeText(snapshotOrderNature(snapshot))})`;
  const confirmedHistoryUnchanged = (snapshot, alias='s') => `NOT EXISTS (
    SELECT 1 FROM calc.quote_scheme_snapshot history_snapshot,
      jsonb_array_elements(CASE WHEN jsonb_typeof(history_snapshot.snapshot_payload#>'{quote_management,versions}')='array'
        THEN history_snapshot.snapshot_payload#>'{quote_management,versions}' ELSE '[]'::jsonb END) old_version
    WHERE history_snapshot.scheme_id=${alias}.scheme_id AND old_version->>'confirmed'='true'
      AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(${sqlUnicodeText(JSON.stringify(
        Array.isArray(snapshot.quote_management?.versions) ? snapshot.quote_management.versions : []))}::jsonb) new_version
        WHERE new_version->>'version'=old_version->>'version'
          AND (new_version-'sealed')=(old_version-'sealed')))`;

  const create = async (principal, input, { sourceNo = null } = {}) => {
    principal=currentQuotePrincipal()||principal;
    input=sessionOperator(principal,input);
    const snapshot = snapshotValue(input);
    const operatorName = operatorNameValue(input);
    const summary = summaryFromSnapshot(snapshot);
    const p = principalValues(principal);
    let sourceSql = 'NULL';
    let sourceVersionSql = 'NULL';
    const versionSql = '1';
    const status = 'DRAFT';
    if (sourceNo) {
      if (!validSchemeNo(sourceNo)) throw Object.assign(new Error('invalid source scheme number'), { statusCode: 400 });
      sourceSql = `(SELECT scheme_id FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(sourceNo)} AND ${permissionSql(principal, 's')})`;
      sourceVersionSql = `(SELECT version_no FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(sourceNo)} AND ${permissionSql(principal, 's')})`;
    }
    return query(`WITH created AS (
      INSERT INTO calc.quote_scheme (
        scheme_no,status,version_no,source_scheme_id,source_version_no,company_name,product_summary,quoted_amount,
        creator_user_id,creator_name_snapshot,creator_name_entered,creator_identity_mode,creator_department_id,
        last_editor_user_id,last_editor_name_snapshot
      ) VALUES (calc.next_quote_scheme_number(),${sqlUnicodeText(status)},${versionSql},${sourceSql},${sourceVersionSql},
        ${sqlUnicodeText(summary.company)},${sqlUnicodeText(summary.productSummary)},${sqlNumber(summary.amount)},
        ${p.id},${p.name},${sqlUnicodeText(operatorName)},${p.identityMode},${p.dept},${p.id},${sqlUnicodeText(operatorName)})
      RETURNING *
    ), snap AS (
      INSERT INTO calc.quote_scheme_snapshot (scheme_id,snapshot_payload,saved_by_user_id,saved_by_name_snapshot)
      SELECT scheme_id,jsonb_set(${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb,'{document}',
        (CASE WHEN jsonb_typeof(${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb->'document')='object'
          THEN ${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb->'document' ELSE '{}'::jsonb END)
        || jsonb_build_object('scheme_no',scheme_no,'version_no',version_no,
          'quote_date',to_char(created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD')),TRUE),
        ${p.id},${sqlUnicodeText(operatorName)} FROM created
    ), lines AS (
      INSERT INTO calc.quote_scheme_item (scheme_id,line_no,item_payload)
      SELECT c.scheme_id, row.ordinality::integer, row.value FROM created c,
        jsonb_array_elements(${sqlUnicodeText(JSON.stringify(snapshot.draft_items || []))}::jsonb) WITH ORDINALITY row
    ), audit AS (
      INSERT INTO calc.quote_scheme_audit (scheme_id,action,to_status,actor_user_id,actor_name_snapshot,detail)
      SELECT scheme_id,${sqlUnicodeText(sourceNo ? 'COPIED' : 'CREATED')},status,${p.id},${sqlUnicodeText(operatorName)},
        jsonb_build_object('source_scheme_no',${sqlUnicodeText(sourceNo)},'identity_mode',${p.auditMode}) FROM created
    ) SELECT jsonb_build_object('scheme_no',scheme_no,'status',status,'version_no',version_no,
      'lock_version',lock_version,'created_at',created_at,'updated_at',updated_at,
      'quote_management_historical_export',TRUE) FROM created;`);
  };

  const get = async (principal, schemeNo) => {
    principal=currentQuotePrincipal()||principal;
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    return query(`SELECT COALESCE((SELECT jsonb_build_object(
      'found',TRUE,'scheme_no',s.scheme_no,'status',s.status,'version_no',s.version_no,
      'source_kind',COALESCE(to_jsonb(s)->>'source_kind','QUOTE'),'contract_record_id',to_jsonb(s)->>'contract_record_id',
      'contract_amount',to_jsonb(s)->'contract_amount','contracted_at',to_jsonb(s)->>'contracted_at','contract_source_kind',to_jsonb(s)->>'contract_source_kind',
      'can_write',(${writePermissionSql(principal,'s')}),
      'source_scheme_no',source.scheme_no,'source_version_no',s.source_version_no,'company_name',s.company_name,'product_summary',s.product_summary,
      'quoted_amount',s.quoted_amount,'creator_user_id',s.creator_user_id,'creator_name',s.creator_name_entered,
      'creator_identity_mode',s.creator_identity_mode,
      'last_editor_name',s.last_editor_name_snapshot,'lock_version',s.lock_version,
      'created_at',s.created_at,'updated_at',s.updated_at,'snapshot',snap.snapshot_payload,
      'order_nature',${orderNatureSql('snap.snapshot_payload')},
      'order_nature_locked',EXISTS(SELECT 1 FROM calc.quote_scheme_version nl WHERE nl.scheme_id=s.scheme_id AND ${orderNatureSql('nl.snapshot_payload')}<>'UNCLASSIFIED'),
      'quote_management_historical_export',TRUE)
      FROM calc.quote_scheme s JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
      LEFT JOIN calc.quote_scheme source ON source.scheme_id=s.source_scheme_id
      WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${permissionSql(principal, 's')}),
      '{"found":false}'::jsonb)::text;`);
  };

  const list = async (principal, filters = {}) => {
    principal=currentQuotePrincipal()||principal;
    const page = Math.max(1, Math.min(100000, Number(filters.page) || 1));
    const pageSize = Math.max(10, Math.min(100, Number(filters.page_size) || 20));
    const where = [permissionSql(principal, 's')];
    const search = String(filters.search || '').trim();
    if (search) where.push(`(s.scheme_no ILIKE ${sqlUnicodeText(`%${escapeLike(search)}%`)} ESCAPE '\\'
      OR s.company_name ILIKE ${sqlUnicodeText(`%${escapeLike(search)}%`)} ESCAPE '\\'
      OR s.product_summary ILIKE ${sqlUnicodeText(`%${escapeLike(search)}%`)} ESCAPE '\\')`);
    for (const [column, key] of [['scheme_no','scheme_no'],['company_name','company'],['product_summary','product'],['creator_name_entered','creator']]) {
      const value = String(filters[key] || '').trim();
      if (value) where.push(`s.${column} ILIKE ${sqlUnicodeText(`%${escapeLike(value)}%`)} ESCAPE '\\'`);
    }
    if (STATUSES.includes(String(filters.status || '').toUpperCase())) where.push(`s.status=${sqlUnicodeText(String(filters.status).toUpperCase())}`);
    if (filters.order_nature) where.push(`${orderNatureSql('snap.snapshot_payload')}=${sqlUnicodeText(validateOrderNature(filters.order_nature))}`);
    const dates = Object.fromEntries(['updated_from','updated_to'].map(key=>[key,String(filters[key] || '').trim()]));
    for (const value of Object.values(dates)) {
      if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0,4))<1 || !Number.isFinite(Date.parse(value+'T00:00:00Z'))
        || new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)) {
        throw Object.assign(new Error('更新时间请输入 YYYY-MM-DD 格式的有效日期。'),{statusCode:400});
      }
    }
    if (dates.updated_from && dates.updated_to && dates.updated_from > dates.updated_to)
      throw Object.assign(new Error('开始日期不能晚于结束日期。'),{statusCode:400});
    // Inclusive calendar dates follow the same Shanghai business clock as the UI.
    if (dates.updated_from) where.push(`s.updated_at >= (${sqlUnicodeText(dates.updated_from)}::date::timestamp AT TIME ZONE 'Asia/Shanghai')`);
    if (dates.updated_to) where.push(`s.updated_at < ((${sqlUnicodeText(dates.updated_to)}::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')`);
    const predicate = where.join(' AND ');
    return query(`WITH matched AS (
      SELECT s.*, source.scheme_no AS source_scheme_no,(${writePermissionSql(principal,'s')}) AS can_write,
        CASE WHEN (snap.snapshot_payload#>>'{quote_management,current}') ~ '^[1-9][0-9]*$'
          THEN (snap.snapshot_payload#>>'{quote_management,current}')::numeric ELSE s.version_no END AS quote_version,
        ${orderNatureSql('snap.snapshot_payload')} AS order_nature,count(*) OVER() AS total_count
      FROM calc.quote_scheme s LEFT JOIN calc.quote_scheme source ON source.scheme_id=s.source_scheme_id
      LEFT JOIN calc.quote_scheme_snapshot snap ON snap.scheme_id=s.scheme_id
      WHERE ${predicate} ORDER BY s.updated_at DESC,s.scheme_id DESC
      LIMIT ${pageSize} OFFSET ${(page - 1) * pageSize}
    ) SELECT jsonb_build_object('page',${page},'page_size',${pageSize},
      'total',COALESCE(max(total_count),0),'items',COALESCE(jsonb_agg(jsonb_build_object(
        'scheme_no',scheme_no,'status',status,'version_no',version_no,'quote_version',quote_version,'source_scheme_no',source_scheme_no,'source_version_no',source_version_no,
        'company_name',company_name,'product_summary',product_summary,'quoted_amount',quoted_amount,'can_write',can_write,'order_nature',order_nature,
        'source_kind',COALESCE(to_jsonb(matched)->>'source_kind','QUOTE'),'contract_record_id',to_jsonb(matched)->>'contract_record_id',
        'contract_amount',to_jsonb(matched)->'contract_amount','contracted_at',to_jsonb(matched)->>'contracted_at',
        'creator_name',creator_name_entered,'creator_identity_mode',creator_identity_mode,'last_editor_name',last_editor_name_snapshot,
        'lock_version',lock_version,'updated_at',updated_at) ORDER BY updated_at DESC,scheme_id DESC),'[]'::jsonb))::text FROM matched;`);
  };

  const save = async (principal, schemeNo, input) => {
    principal=currentQuotePrincipal()||principal;
    input=sessionOperator(principal,input);
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const snapshot = snapshotValue(input);
    const operatorName = operatorNameValue(input);
    if (!positiveVersion(input.expected_version)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const summary = summaryFromSnapshot(snapshot); const p = principalValues(principal);
    const itemsJson = JSON.stringify(snapshot.draft_items || []);
    const result = await query(`WITH allowed AS (
      SELECT s.* FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
        AND ${writePermissionSql(principal, 's')} AND s.status IN ('DRAFT','REVISING')
        AND ${natureUnchanged(snapshot)}
        AND ${confirmedHistoryUnchanged(snapshot)}
        AND s.lock_version=${sqlNumber(input.expected_version)} FOR UPDATE
    ), updated AS (
      UPDATE calc.quote_scheme s SET company_name=${sqlUnicodeText(summary.company)},
        product_summary=${sqlUnicodeText(summary.productSummary)},quoted_amount=${sqlNumber(summary.amount)},
        last_editor_user_id=${p.id},last_editor_name_snapshot=${sqlUnicodeText(operatorName)},updated_at=now(),lock_version=s.lock_version+1
      FROM allowed a WHERE s.scheme_id=a.scheme_id RETURNING s.*
    ), snap AS (
      INSERT INTO calc.quote_scheme_snapshot (scheme_id,snapshot_payload,saved_at,saved_by_user_id,saved_by_name_snapshot)
      SELECT scheme_id,jsonb_set(${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb,'{document}',
        (CASE WHEN jsonb_typeof(${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb->'document')='object'
          THEN ${sqlUnicodeText(JSON.stringify(snapshot))}::jsonb->'document' ELSE '{}'::jsonb END)
        || jsonb_build_object('scheme_no',scheme_no,'version_no',version_no),TRUE),
        now(),${p.id},${sqlUnicodeText(operatorName)} FROM updated
      ON CONFLICT (scheme_id) DO UPDATE SET snapshot_payload=EXCLUDED.snapshot_payload,saved_at=now(),
        saved_by_user_id=EXCLUDED.saved_by_user_id,saved_by_name_snapshot=EXCLUDED.saved_by_name_snapshot
    ), cleared AS (DELETE FROM calc.quote_scheme_item WHERE scheme_id IN (SELECT scheme_id FROM updated) RETURNING scheme_id),
    lines AS (INSERT INTO calc.quote_scheme_item (scheme_id,line_no,item_payload)
      SELECT u.scheme_id,row.ordinality::integer,row.value FROM updated u CROSS JOIN (SELECT count(*) FROM cleared) cleared_count,
        jsonb_array_elements(${sqlUnicodeText(itemsJson)}::jsonb) WITH ORDINALITY row),
    audit AS (INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot,detail)
      SELECT scheme_id,'SAVED',status,status,${p.id},${sqlUnicodeText(operatorName)},
        jsonb_build_object('lock_version',lock_version) FROM updated)
    SELECT COALESCE((SELECT jsonb_build_object('saved',TRUE,'scheme_no',scheme_no,'status',status,
      'lock_version',lock_version,'updated_at',updated_at) FROM updated),'{"saved":false,"conflict":true}'::jsonb)::text;`);
    if (!result?.saved) throw Object.assign(new Error('方案已被他人修改、当前状态只读、无权限或已确认调价历史被改动，请重新打开。'), { statusCode: 409 });
    return result;
  };

  const transition = async (principal, schemeNo, action, expectedVersion, operatorNameInput) => {
    principal=currentQuotePrincipal()||principal;
    if(isNamePrincipal(principal))operatorNameInput=principal.displayName;
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const config = {
      archive: { from: ['QUOTED','CONTRACT'], to: 'ARCHIVED' }, restore: { from: ['ARCHIVED'], to: 'QUOTED' },
      void: { from: ['DRAFT','QUOTED','CONTRACT','REVISING','ARCHIVED'], to: 'VOID' },
    }[action];
    if (!config || !positiveVersion(expectedVersion)) throw Object.assign(new Error('invalid transition request'), { statusCode: 400 });
    const operatorName = operatorNameValue({operator_name:operatorNameInput});
    for (const from of config.from) assertTransition(from, config.to);
    const p = principalValues(principal);
    const result = await query(`WITH target AS (
      SELECT s.* FROM calc.quote_scheme s
      WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${writePermissionSql(principal, 's')}
        AND s.status=ANY(ARRAY[${config.from.map(sqlUnicodeText).join(',')}]) AND s.lock_version=${sqlNumber(expectedVersion)}
      FOR UPDATE
    ), changed AS (
      UPDATE calc.quote_scheme s SET status=CASE WHEN ${sqlUnicodeText(config.to)}='QUOTED'
        AND (to_jsonb(t)->>'contract_version_no')::integer=t.version_no AND to_jsonb(t)->>'contract_record_id' IS NOT NULL
        THEN 'CONTRACT' ELSE ${sqlUnicodeText(config.to)} END,lock_version=s.lock_version+1,
        updated_at=now(),last_editor_user_id=${p.id},last_editor_name_snapshot=${sqlUnicodeText(operatorName)},
        archived_at=CASE WHEN ${sqlUnicodeText(config.to)}='ARCHIVED' THEN now() ELSE s.archived_at END,
        voided_at=CASE WHEN ${sqlUnicodeText(config.to)}='VOID' THEN now() ELSE s.voided_at END
      FROM target t WHERE s.scheme_id=t.scheme_id
      RETURNING s.*
    ), audit AS (INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot)
      SELECT c.scheme_id,${sqlUnicodeText(action.toUpperCase())},t.status,c.status,${p.id},${sqlUnicodeText(operatorName)}
      FROM changed c JOIN target t USING(scheme_id))
    SELECT COALESCE((SELECT jsonb_build_object('changed',TRUE,'status',status,'lock_version',lock_version,'updated_at',updated_at) FROM changed),
      '{"changed":false,"conflict":true}'::jsonb)::text;`);
    if (!result?.changed) throw Object.assign(new Error('状态已变化、无权限或版本冲突。'), { statusCode: 409 });
    return result;
  };

  const revision = async (principal, schemeNo, expectedVersion, operatorNameInput) => {
    principal=currentQuotePrincipal()||principal;
    if(isNamePrincipal(principal))operatorNameInput=principal.displayName;
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    if (!positiveVersion(expectedVersion)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const operatorName = operatorNameValue({operator_name:operatorNameInput});
    const p = principalValues(principal);
    const result = await query(`WITH target AS (
      SELECT s.*,snap.snapshot_payload FROM calc.quote_scheme s
      JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
      WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${writePermissionSql(principal, 's')}
        AND s.status IN ('QUOTED','CONTRACT') AND COALESCE(to_jsonb(s)->>'source_kind','QUOTE')='QUOTE' AND s.lock_version=${sqlNumber(expectedVersion)} FOR UPDATE
    ), frozen AS (
      INSERT INTO calc.quote_scheme_version(scheme_id,version_no,source_version_no,status,snapshot_payload,quoted_at)
      SELECT scheme_id,version_no,source_version_no,'QUOTED',snapshot_payload,quoted_at FROM target
      ON CONFLICT (scheme_id,version_no) DO NOTHING
    ), changed AS (
      UPDATE calc.quote_scheme s SET status='REVISING',source_version_no=s.version_no,version_no=s.version_no+1,
        lock_version=s.lock_version+1,updated_at=now(),last_editor_user_id=${p.id},last_editor_name_snapshot=${sqlUnicodeText(operatorName)}
      FROM target t WHERE s.scheme_id=t.scheme_id RETURNING s.*
    ), revision_snapshot AS (
      UPDATE calc.quote_scheme_snapshot snap SET snapshot_payload=jsonb_set(snap.snapshot_payload,'{document}',
        (CASE WHEN jsonb_typeof(snap.snapshot_payload->'document')='object'
          THEN snap.snapshot_payload->'document' ELSE '{}'::jsonb END)
        || jsonb_build_object('scheme_no',c.scheme_no,'version_no',c.version_no,
          'quote_date',to_char(c.updated_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD')),TRUE),
        saved_at=now(),saved_by_user_id=${p.id},saved_by_name_snapshot=${sqlUnicodeText(operatorName)}
      FROM changed c WHERE snap.scheme_id=c.scheme_id RETURNING snap.scheme_id
    ), audit AS (
      INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot,detail)
      SELECT c.scheme_id,'REVISION_CREATED',t.status,'REVISING',${p.id},${sqlUnicodeText(operatorName)},jsonb_build_object('source_version_no',c.source_version_no) FROM changed c JOIN target t USING(scheme_id)
    ) SELECT COALESCE((SELECT jsonb_build_object('changed',TRUE,'scheme_no',scheme_no,'status',status,
      'version_no',version_no,'source_version_no',source_version_no,'lock_version',lock_version,'updated_at',updated_at) FROM changed),
      '{"changed":false,"conflict":true}'::jsonb)::text;`);
    if (!result?.changed) throw Object.assign(new Error('仅最新已报价版本可创建修订版，且必须匹配最新版本。'), { statusCode: 409 });
    return result;
  };

  const registerResult = async (principal, schemeNo, input, contractConfirmation=false) => {
    principal=currentQuotePrincipal()||principal;
    input=sessionOperator(principal,input);
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const kind = String(input.kind || 'XLSX').toUpperCase();
    if (!(contractConfirmation?kind==='CONTRACT':['PRINT','PREVIEW','XLSX'].includes(kind)) || typeof input.succeeded !== 'boolean') {
      throw Object.assign(new Error('kind and succeeded are required'), { statusCode: 400 });
    }
    if (!positiveVersion(input.expected_version)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const operatorName = operatorNameValue(input);
    // Preview is non-final. Contract confirmation is an explicit separate
    // action: it freezes the quote without inventing a print/export receipt.
    const formalSuccess = input.succeeded && kind !== 'PREVIEW';
    const frozenSnapshot = formalSuccess ? snapshotValue(input) : null;
    if (formalSuccess) validateOrderNature(snapshotOrderNature(frozenSnapshot), true);
    if (input.historical_quote_version !== undefined) {
      const version = Number(input.historical_quote_version);
      if (!Number.isInteger(version) || version < 1 || !formalSuccess || !Array.isArray(frozenSnapshot.draft_items)) {
        throw Object.assign(new Error('invalid historical quote export'), {statusCode:400});
      }
      const p = principalValues(principal);
      const detail = {...input.detail, historical_quote_version:version,
        export_registration_id:frozenSnapshot.document?.export_registration_id || null};
      const result = await query(`WITH target AS (
        SELECT s.* FROM calc.quote_scheme s JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
        WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${writePermissionSql(principal, 's')}
          AND s.lock_version=${sqlNumber(input.expected_version)}
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(CASE
            WHEN jsonb_typeof(snap.snapshot_payload->'quote_management'->'versions')='array'
            THEN snap.snapshot_payload->'quote_management'->'versions' ELSE '[]'::jsonb END) entry
            WHERE entry->>'version'=${sqlUnicodeText(String(version))}
              AND (entry->>'version'<>snap.snapshot_payload->'quote_management'->>'current'
                OR entry->>'confirmed'='true')
              AND entry->'items'=${sqlUnicodeText(JSON.stringify(frozenSnapshot.draft_items))}::jsonb
              AND COALESCE(entry->>'order_nature','UNCLASSIFIED')=${sqlUnicodeText(snapshotOrderNature(frozenSnapshot))}
              AND entry->>'company'=${sqlUnicodeText(String(frozenSnapshot.company || ''))})
        FOR UPDATE OF s),
        logged AS (INSERT INTO calc.quote_scheme_export(scheme_id,export_kind,succeeded,actor_user_id,actor_name_snapshot,detail)
          SELECT scheme_id,${sqlUnicodeText(kind)},TRUE,${p.id},${sqlUnicodeText(operatorName)},
            ${sqlUnicodeText(JSON.stringify(detail))}::jsonb FROM target RETURNING scheme_id)
        SELECT COALESCE((SELECT jsonb_build_object('recorded',TRUE,'formal_success',TRUE,
          'historical',TRUE,'status',s.status,'lock_version',s.lock_version)
          FROM target s JOIN logged USING(scheme_id)), '{"recorded":false}'::jsonb)::text;`);
      if (!result?.recorded) throw Object.assign(new Error('历史报价内容或当前版本已变化，不能登记该导出。'), {statusCode:409});
      return result;
    }
    const summary = frozenSnapshot ? summaryFromSnapshot(frozenSnapshot) : {company:'',productSummary:'',amount:0};
    const p = principalValues(principal);
    const result = await query(`WITH target AS (SELECT s.* FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
      AND COALESCE(to_jsonb(s)->>'source_kind','QUOTE')='QUOTE'
      AND ${writePermissionSql(principal, 's')} AND s.lock_version=${sqlNumber(input.expected_version)}
      ${contractConfirmation?"AND s.status IN ('DRAFT','REVISING')":''}
      ${formalSuccess ? `AND ${natureUnchanged(frozenSnapshot)} AND ${confirmedHistoryUnchanged(frozenSnapshot)}` : ''} FOR UPDATE),
    logged AS (${contractConfirmation?`INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot,detail)
      SELECT scheme_id,'CONTRACT_CONFIRMED',status,'QUOTED',${p.id},${sqlUnicodeText(operatorName)},
        ${sqlUnicodeText(JSON.stringify({quote_version:displayVersion(frozenSnapshot,1),request_id:frozenSnapshot.document.contract_confirmation_id}))}::jsonb FROM target RETURNING scheme_id`:`INSERT INTO calc.quote_scheme_export(scheme_id,export_kind,succeeded,actor_user_id,actor_name_snapshot,detail)
      SELECT scheme_id,${sqlUnicodeText(kind)},${input.succeeded ? 'TRUE':'FALSE'},${p.id},${sqlUnicodeText(operatorName)},
        ${sqlUnicodeText(JSON.stringify(input.detail || {}))}::jsonb FROM target RETURNING scheme_id`}),
    changed AS (UPDATE calc.quote_scheme s SET status=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN 'QUOTED' ELSE s.status END,
      company_name=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN ${sqlUnicodeText(summary.company)} ELSE s.company_name END,
      product_summary=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN ${sqlUnicodeText(summary.productSummary)} ELSE s.product_summary END,
      quoted_amount=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN ${sqlNumber(summary.amount)} ELSE s.quoted_amount END,
      has_successful_export=s.has_successful_export OR ${formalSuccess ? 'TRUE':'FALSE'},quoted_at=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} THEN COALESCE(s.quoted_at,now()) ELSE s.quoted_at END,
      updated_at=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN now() ELSE s.updated_at END,
      lock_version=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN s.lock_version+1 ELSE s.lock_version END,
      last_editor_user_id=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN ${p.id} ELSE s.last_editor_user_id END,
      last_editor_name_snapshot=CASE WHEN ${formalSuccess ? 'TRUE':'FALSE'} AND s.status IN ('DRAFT','REVISING') THEN ${sqlUnicodeText(operatorName)} ELSE s.last_editor_name_snapshot END
      WHERE s.scheme_id IN (SELECT scheme_id FROM logged) RETURNING s.*),
    status_audit AS (INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot)
      SELECT c.scheme_id,'EXPORT_CONFIRMED',t.status,c.status,${p.id},${sqlUnicodeText(operatorName)} FROM changed c JOIN target t USING(scheme_id)
      WHERE ${formalSuccess&&!contractConfirmation ? 'TRUE':'FALSE'} AND t.status IS DISTINCT FROM c.status),
    snap AS (INSERT INTO calc.quote_scheme_snapshot(scheme_id,snapshot_payload,saved_at,saved_by_user_id,saved_by_name_snapshot)
      SELECT scheme_id,jsonb_set(${sqlUnicodeText(JSON.stringify(frozenSnapshot || {}))}::jsonb,'{document}',
        (CASE WHEN jsonb_typeof(${sqlUnicodeText(JSON.stringify(frozenSnapshot || {}))}::jsonb->'document')='object'
          THEN ${sqlUnicodeText(JSON.stringify(frozenSnapshot || {}))}::jsonb->'document' ELSE '{}'::jsonb END)
        || jsonb_build_object('scheme_no',scheme_no,'version_no',version_no),TRUE),
        now(),${p.id},${sqlUnicodeText(operatorName)} FROM changed
      WHERE ${formalSuccess ? 'TRUE':'FALSE'} AND EXISTS (
        SELECT 1 FROM target t WHERE t.scheme_id=changed.scheme_id AND t.status IN ('DRAFT','REVISING'))
      ON CONFLICT (scheme_id) DO UPDATE SET snapshot_payload=EXCLUDED.snapshot_payload,saved_at=now(),
        saved_by_user_id=EXCLUDED.saved_by_user_id,saved_by_name_snapshot=EXCLUDED.saved_by_name_snapshot
      RETURNING scheme_id,snapshot_payload),
    cleared AS (DELETE FROM calc.quote_scheme_item i WHERE i.scheme_id IN (
      SELECT t.scheme_id FROM target t WHERE t.status IN ('DRAFT','REVISING')) AND ${formalSuccess ? 'TRUE':'FALSE'} RETURNING scheme_id),
    lines AS (INSERT INTO calc.quote_scheme_item(scheme_id,line_no,item_payload)
      SELECT c.scheme_id,row.ordinality::integer,row.value FROM changed c CROSS JOIN (SELECT count(*) FROM cleared) cleared_count,
        jsonb_array_elements(${sqlUnicodeText(JSON.stringify(frozenSnapshot?.draft_items || []))}::jsonb) WITH ORDINALITY row
      WHERE ${formalSuccess ? 'TRUE':'FALSE'} AND EXISTS (
        SELECT 1 FROM target t WHERE t.scheme_id=c.scheme_id AND t.status IN ('DRAFT','REVISING'))),
    versioned AS (INSERT INTO calc.quote_scheme_version(scheme_id,version_no,source_version_no,status,snapshot_payload,quoted_at)
      SELECT c.scheme_id,c.version_no,c.source_version_no,'QUOTED',saved_snapshot.snapshot_payload,c.quoted_at
      FROM changed c JOIN snap saved_snapshot USING(scheme_id)
      WHERE ${formalSuccess ? 'TRUE':'FALSE'} AND EXISTS (
        SELECT 1 FROM target t WHERE t.scheme_id=c.scheme_id AND t.status IN ('DRAFT','REVISING'))
      ON CONFLICT (scheme_id,version_no) DO NOTHING)
    SELECT COALESCE((SELECT jsonb_build_object('recorded',TRUE,'status',status,'lock_version',lock_version,
      'formal_success',${formalSuccess ? 'TRUE':'FALSE'}${contractConfirmation?`, 'source_version_no',version_no,'quote_version',${displayVersion(frozenSnapshot,1)}`:''}) FROM changed),'{"recorded":false}'::jsonb)::text;`);
    if (!result?.recorded) throw Object.assign(new Error('方案已被他人修改或无权限，请重新打开后再登记导出结果。'), {statusCode:409});
    return result;
  };

  const exportResult=(principal,schemeNo,input)=>registerResult(principal,schemeNo,input);
  const confirmForContract=async(principal,schemeNo,input)=>{
    principal=currentQuotePrincipal()||principal;
    if(!principal?.userId||String(principal.userId).startsWith('shared-client:'))throw Object.assign(Error('请使用姓名会话生成合同'),{statusCode:401});
    if(!validSchemeNo(schemeNo)||!positiveVersion(input.expected_version)||!positiveVersion(input.quote_version)||
       !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(String(input.request_id||''))||input.historical_quote_version!==undefined)
      throw Object.assign(Error('当前报价版本或确认编号无效'),{statusCode:400});
    const snapshot=snapshotValue(input);
    if(snapshotOrderNature(snapshot)!=='EXTERNAL')throw Object.assign(Error('仅外部报价可生成合同'),{statusCode:409});
    if(!String(snapshot.company||'').trim())throw Object.assign(Error('请先填写本次报价客户'),{statusCode:400});
    if(displayVersion(snapshot,1)!==Number(input.quote_version))throw Object.assign(Error('当前查看版本与提交版本不一致'),{statusCode:409});
    const current=snapshot.quote_management?.versions?.find(v=>v.version===Number(input.quote_version));
    if(current?.pending_confirmation)throw Object.assign(Error('当前修订内容尚未确认，请先核对报价'),{statusCode:409});
    try{contractQuote(snapshot,'QUICK');}catch(error){error.statusCode=400;throw error;}
    const stable=value=>JSON.stringify(value,(_k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
    const fingerprint=crypto.createHash('sha256').update(stable(snapshot)).digest('hex');
    const prior=await query(`SELECT COALESCE((SELECT jsonb_build_object('recorded',TRUE,'formal_success',TRUE,'status',s.status,'lock_version',s.lock_version,
       'source_version_no',v.version_no,'quote_version',${Number(input.quote_version)},'fingerprint',v.snapshot_payload#>>'{document,contract_confirmation_sha256}')
       FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id) WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
       AND s.status<>'VOID' AND ${writePermissionSql(principal,'s')} AND v.snapshot_payload#>>'{document,contract_confirmation_id}'=${sqlUnicodeText(input.request_id)}),'null'::jsonb)::text;`);
    if(prior){if(prior.fingerprint!==fingerprint)throw Object.assign(Error('本次确认编号已对应其他报价内容'),{statusCode:409});const {fingerprint:_,...result}=prior;return {...result,reused:true};}
    snapshot.document={...snapshot.document,contract_confirmation_id:input.request_id,contract_confirmation_sha256:fingerprint};
    return registerResult(principal,schemeNo,{...input,snapshot,kind:'CONTRACT',succeeded:true},true);
  };

  const removeDraft = async (principal, schemeNo, expectedVersion, operatorNameInput) => {
    principal=currentQuotePrincipal()||principal;
    if(isNamePrincipal(principal))operatorNameInput=principal.displayName;
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    if (!positiveVersion(expectedVersion)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    operatorNameValue({operator_name:operatorNameInput});
    const result = await query(`WITH deleted AS (DELETE FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
      AND ${writePermissionSql(principal, 's')} AND s.status='DRAFT' AND NOT s.has_successful_export
      AND s.lock_version=${sqlNumber(expectedVersion)} RETURNING scheme_no)
      SELECT jsonb_build_object('deleted',EXISTS(SELECT 1 FROM deleted))::text;`);
    if (!result?.deleted) throw Object.assign(new Error('仅未使用草稿可删除，且必须匹配最新版本。'), { statusCode: 409 });
    return result;
  };

  return { create, get, list, save, transition, revision, exportResult, confirmForContract, removeDraft };
};

export {
  ROLES, STATUSES, TRANSITIONS, apiKeyHash, assertTransition, canReadScheme,
  createQuoteSchemeService, loadPrincipalMap, operatorNameValue, resolvePrincipal,
  resolveQuoteSchemePrincipal, summaryFromSnapshot,
  permissionSql, writePermissionSql,
};
