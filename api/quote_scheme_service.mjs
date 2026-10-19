import crypto from 'node:crypto';

const STATUSES = Object.freeze(['DRAFT', 'QUOTED', 'REVISING', 'ARCHIVED', 'VOID']);
const ROLES = Object.freeze(['USER', 'DEPARTMENT_MANAGER', 'ADMIN']);
const TRANSITIONS = Object.freeze({
  DRAFT: new Set(['QUOTED', 'VOID']),
  QUOTED: new Set(['ARCHIVED', 'VOID']),
  REVISING: new Set(['QUOTED', 'VOID']),
  ARCHIVED: new Set(['QUOTED', 'VOID']),
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
  const key = String(req?.headers?.['x-ai-quote-key'] || '');
  const mapped = principalMap.get(apiKeyHash(key));
  if (mapped) return Object.freeze({...mapped, identityMode:'AUTHENTICATED'});
  if (String(sharedApiKey || '') && key === String(sharedApiKey)) {
    return Object.freeze({
      userId:`shared-client:${apiKeyHash(key).slice(0, 24)}`,
      displayName:'共享报价客户端', departmentId:null, role:'ADMIN', identityMode:'SELF_REPORTED',
    });
  }
  return resolvePrincipal(req, principalMap);
};

const assertTransition = (from, to) => {
  if (!STATUSES.includes(from) || !STATUSES.includes(to) || !TRANSITIONS[from].has(to)) {
    const error = new Error(`invalid quote scheme status transition: ${from} -> ${to}`);
    error.statusCode = 409;
    throw error;
  }
};

const canReadScheme = (principal, scheme) => principal.role === 'ADMIN'
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
  return value;
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
    identityMode: sqlUnicodeText(p.identityMode || 'AUTHENTICATED'),
  });

  const create = async (principal, input, { sourceNo = null } = {}) => {
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
        jsonb_build_object('source_scheme_no',${sqlUnicodeText(sourceNo)},'identity_mode',${p.identityMode}) FROM created
    ) SELECT jsonb_build_object('scheme_no',scheme_no,'status',status,'version_no',version_no,
      'lock_version',lock_version,'created_at',created_at,'updated_at',updated_at) FROM created;`);
  };

  const get = async (principal, schemeNo) => {
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    return query(`SELECT COALESCE((SELECT jsonb_build_object(
      'found',TRUE,'scheme_no',s.scheme_no,'status',s.status,'version_no',s.version_no,
      'source_scheme_no',source.scheme_no,'source_version_no',s.source_version_no,'company_name',s.company_name,'product_summary',s.product_summary,
      'quoted_amount',s.quoted_amount,'creator_user_id',s.creator_user_id,'creator_name',s.creator_name_entered,
      'creator_identity_mode',s.creator_identity_mode,
      'last_editor_name',s.last_editor_name_snapshot,'lock_version',s.lock_version,
      'created_at',s.created_at,'updated_at',s.updated_at,'snapshot',snap.snapshot_payload)
      FROM calc.quote_scheme s JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
      LEFT JOIN calc.quote_scheme source ON source.scheme_id=s.source_scheme_id
      WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${permissionSql(principal, 's')}),
      '{"found":false}'::jsonb)::text;`);
  };

  const list = async (principal, filters = {}) => {
    const page = Math.max(1, Math.min(100000, Number(filters.page) || 1));
    const pageSize = Math.max(10, Math.min(100, Number(filters.page_size) || 20));
    const where = [permissionSql(principal, 's')];
    for (const [column, key] of [['scheme_no','scheme_no'],['company_name','company'],['product_summary','product'],['creator_name_entered','creator']]) {
      const value = String(filters[key] || '').trim();
      if (value) where.push(`s.${column} ILIKE ${sqlUnicodeText(`%${escapeLike(value)}%`)} ESCAPE '\\'`);
    }
    if (STATUSES.includes(String(filters.status || '').toUpperCase())) where.push(`s.status=${sqlUnicodeText(String(filters.status).toUpperCase())}`);
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(filters.updated_from || ''))) where.push(`s.updated_at >= ${sqlUnicodeText(filters.updated_from)}::date`);
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(filters.updated_to || ''))) where.push(`s.updated_at < (${sqlUnicodeText(filters.updated_to)}::date + interval '1 day')`);
    const predicate = where.join(' AND ');
    return query(`WITH matched AS (
      SELECT s.*, source.scheme_no AS source_scheme_no, count(*) OVER() AS total_count
      FROM calc.quote_scheme s LEFT JOIN calc.quote_scheme source ON source.scheme_id=s.source_scheme_id
      WHERE ${predicate} ORDER BY s.updated_at DESC,s.scheme_id DESC
      LIMIT ${pageSize} OFFSET ${(page - 1) * pageSize}
    ) SELECT jsonb_build_object('page',${page},'page_size',${pageSize},
      'total',COALESCE(max(total_count),0),'items',COALESCE(jsonb_agg(jsonb_build_object(
        'scheme_no',scheme_no,'status',status,'version_no',version_no,'source_scheme_no',source_scheme_no,'source_version_no',source_version_no,
        'company_name',company_name,'product_summary',product_summary,'quoted_amount',quoted_amount,
        'creator_name',creator_name_entered,'creator_identity_mode',creator_identity_mode,'last_editor_name',last_editor_name_snapshot,
        'lock_version',lock_version,'updated_at',updated_at) ORDER BY updated_at DESC,scheme_id DESC),'[]'::jsonb))::text FROM matched;`);
  };

  const save = async (principal, schemeNo, input) => {
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const snapshot = snapshotValue(input);
    const operatorName = operatorNameValue(input);
    if (!positiveVersion(input.expected_version)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const summary = summaryFromSnapshot(snapshot); const p = principalValues(principal);
    const itemsJson = JSON.stringify(snapshot.draft_items || []);
    const result = await query(`WITH allowed AS (
      SELECT s.* FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
        AND ${writePermissionSql(principal, 's')} AND s.status IN ('DRAFT','REVISING')
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
    if (!result?.saved) throw Object.assign(new Error('方案已被他人修改、当前状态只读或无权限，请重新打开。'), { statusCode: 409 });
    return result;
  };

  const transition = async (principal, schemeNo, action, expectedVersion, operatorNameInput) => {
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const config = {
      archive: { from: ['QUOTED'], to: 'ARCHIVED' }, restore: { from: ['ARCHIVED'], to: 'QUOTED' },
      void: { from: ['DRAFT','QUOTED','REVISING','ARCHIVED'], to: 'VOID' },
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
      UPDATE calc.quote_scheme s SET status=${sqlUnicodeText(config.to)},lock_version=s.lock_version+1,
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
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    if (!positiveVersion(expectedVersion)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const operatorName = operatorNameValue({operator_name:operatorNameInput});
    const p = principalValues(principal);
    const result = await query(`WITH target AS (
      SELECT s.*,snap.snapshot_payload FROM calc.quote_scheme s
      JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
      WHERE s.scheme_no=${sqlUnicodeText(schemeNo)} AND ${writePermissionSql(principal, 's')}
        AND s.status='QUOTED' AND s.lock_version=${sqlNumber(expectedVersion)} FOR UPDATE
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
      SELECT scheme_id,'REVISION_CREATED','QUOTED','REVISING',${p.id},${sqlUnicodeText(operatorName)},jsonb_build_object('source_version_no',source_version_no) FROM changed
    ) SELECT COALESCE((SELECT jsonb_build_object('changed',TRUE,'scheme_no',scheme_no,'status',status,
      'version_no',version_no,'source_version_no',source_version_no,'lock_version',lock_version,'updated_at',updated_at) FROM changed),
      '{"changed":false,"conflict":true}'::jsonb)::text;`);
    if (!result?.changed) throw Object.assign(new Error('仅最新已报价版本可创建修订版，且必须匹配最新版本。'), { statusCode: 409 });
    return result;
  };

  const exportResult = async (principal, schemeNo, input) => {
    if (!validSchemeNo(schemeNo)) throw Object.assign(new Error('invalid scheme number'), { statusCode: 400 });
    const kind = String(input.kind || 'XLSX').toUpperCase();
    if (!['PRINT','PREVIEW','XLSX'].includes(kind) || typeof input.succeeded !== 'boolean') {
      throw Object.assign(new Error('kind and succeeded are required'), { statusCode: 400 });
    }
    if (!positiveVersion(input.expected_version)) throw Object.assign(new Error('expected_version is required'), { statusCode: 400 });
    const operatorName = operatorNameValue(input);
    // Previewing is deliberately non-final. Only a successful print or XLSX export
    // is evidence that a formal quote document was produced.
    const formalSuccess = input.succeeded && kind !== 'PREVIEW';
    const frozenSnapshot = formalSuccess ? snapshotValue(input) : null;
    const summary = frozenSnapshot ? summaryFromSnapshot(frozenSnapshot) : {company:'',productSummary:'',amount:0};
    const p = principalValues(principal);
    const result = await query(`WITH target AS (SELECT s.* FROM calc.quote_scheme s WHERE s.scheme_no=${sqlUnicodeText(schemeNo)}
      AND ${writePermissionSql(principal, 's')} AND s.lock_version=${sqlNumber(input.expected_version)} FOR UPDATE),
    logged AS (INSERT INTO calc.quote_scheme_export(scheme_id,export_kind,succeeded,actor_user_id,actor_name_snapshot,detail)
      SELECT scheme_id,${sqlUnicodeText(kind)},${input.succeeded ? 'TRUE':'FALSE'},${p.id},${sqlUnicodeText(operatorName)},
        ${sqlUnicodeText(JSON.stringify(input.detail || {}))}::jsonb FROM target RETURNING scheme_id),
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
      WHERE ${formalSuccess ? 'TRUE':'FALSE'} AND t.status IS DISTINCT FROM c.status),
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
      'formal_success',${formalSuccess ? 'TRUE':'FALSE'}) FROM changed),'{"recorded":false}'::jsonb)::text;`);
    if (!result?.recorded) throw Object.assign(new Error('方案已被他人修改或无权限，请重新打开后再登记导出结果。'), {statusCode:409});
    return result;
  };

  const removeDraft = async (principal, schemeNo, expectedVersion, operatorNameInput) => {
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

  return { create, get, list, save, transition, revision, exportResult, removeDraft };
};

export {
  ROLES, STATUSES, TRANSITIONS, apiKeyHash, assertTransition, canReadScheme,
  createQuoteSchemeService, loadPrincipalMap, operatorNameValue, resolvePrincipal,
  resolveQuoteSchemePrincipal, summaryFromSnapshot,
};
