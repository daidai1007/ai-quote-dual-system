import {AsyncLocalStorage} from 'node:async_hooks';
import {authError,ALL_QUOTE_NAMES} from './name_login_service.mjs';

const context=new AsyncLocalStorage();
export const withQuotePrincipal=(principal,callback)=>context.run(principal,callback);
export const currentQuotePrincipal=()=>context.getStore();
export const q=value=>value==null?'NULL':`convert_from(decode('${Buffer.from(String(value),'utf8').toString('hex')}','hex'),'UTF8')`;
export const isNamePrincipal=p=>p?.identityMode==='NAME_ONLY'&&/^name-user:[a-f0-9]{64}$/.test(p.userId||'');
export const canManageAllQuotes=p=>isNamePrincipal(p)&&p.can_manage_all_quotes===true&&ALL_QUOTE_NAMES.includes(p.displayName);
export function effectiveOwnerSql(alias='s'){
  return `COALESCE((SELECT own.owner_user_id FROM calc.quote_name_owner own WHERE own.resource_kind='SCHEME' AND own.resource_key=${alias}.scheme_id::text),CASE WHEN ${alias}.creator_user_id LIKE 'name-user:%' THEN ${alias}.creator_user_id END)`;
}
export function quoteScopeSql(p,alias='s',write=false){
  if(!isNamePrincipal(p))return 'FALSE';
  return canManageAllQuotes(p)||(!write&&p.can_view_all_quotes===true)?'TRUE':`COALESCE(${effectiveOwnerSql(alias)}=${q(p.userId)},FALSE)`;
}
export function resourceScopeSql(p,kind,key,{write=false}={}){
  if(!isNamePrincipal(p))return 'FALSE';
  if(canManageAllQuotes(p)||(!write&&p.can_view_all_quotes===true))return 'TRUE';
  return `EXISTS(SELECT 1 FROM calc.quote_name_owner own WHERE own.resource_kind=${q(kind)} AND own.resource_key=${key} AND own.owner_user_id=${q(p.userId)})`;
}
export function ownerInsertSql(kind,keyExpression,p=currentQuotePrincipal()){
  if(!isNamePrincipal(p))return '';
  return `INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source)
    VALUES(${q(kind)},${keyExpression},${q(p.userId)},${q(p.displayName)},'SESSION_CREATED') ON CONFLICT DO NOTHING;`;
}
export function sessionOperator(principal,input){principal=currentQuotePrincipal()||principal;return isNamePrincipal(principal)?{...input,operator_name:principal.displayName,detail:{...input?.detail,identity_mode:'NAME_ONLY'}}:input;}
export function createPrivateQuoteGuard({runPsql}){
  const query=async sql=>JSON.parse(String(await runPsql(sql)).trim().split(/\r?\n/).at(-1)||'null');
  const ownReference=async(p,id,kind='QUOTE_LINE')=>{
    const fields=kind==='QUOTE_LINE'?['quote_line_id','source_quote_line_id','quick_match_source_line_id']:['quote_id'];
    const reference=fields.map(field=>`EXISTS(SELECT 1 FROM jsonb_path_query(saved.payload,'$.**.${field}') ref(value)
      WHERE ${kind==='QUOTE_LINE'?"lower(ref.value#>>'{}')":"ref.value#>>'{}'"}=${q(kind==='QUOTE_LINE'?String(id).toLowerCase():id)})`).join(' OR ');
    const manage=canManageAllQuotes(p);
    const own=manage?`EXISTS(SELECT 1 FROM calc.quote_name_owner own WHERE own.resource_kind=${q(kind)} AND own.resource_key=${q(id)})`:resourceScopeSql(p,kind,q(id),{write:true});
    // Only server-persisted snapshots of an owned scheme establish references.
    // Revisions can still contain source IDs from an immutable prior version.
    let allowed=await query(`SELECT (${own} OR EXISTS(SELECT 1 FROM calc.quote_scheme s
      CROSS JOIN LATERAL(SELECT snap.snapshot_payload AS payload FROM calc.quote_scheme_snapshot snap WHERE snap.scheme_id=s.scheme_id
        UNION ALL SELECT v.snapshot_payload FROM calc.quote_scheme_version v WHERE v.scheme_id=s.scheme_id) saved
      WHERE ${quoteScopeSql(p,'s',true)} AND (${reference}) ))::text;`);
    if(!allowed&&manage){
      // Old unassigned resources may exist without a scheme/mapping. Permission
      // allows their use, but does not make an invented resource ID valid.
      const table=kind==='QUOTE_LINE'?'calc.attachment_quote_line':kind==='QUOTE_ID'?'calc.dual_quote_result':null;
      if(table&&await query(`SELECT to_jsonb(to_regclass(${q(table)}) IS NOT NULL)::text;`))
        allowed=await query(`SELECT to_jsonb(EXISTS(SELECT 1 FROM ${table} WHERE ${kind==='QUOTE_LINE'?'quote_line_id::text':'quote_id'}=${q(id)}))::text;`);
    }
    if(!allowed)throw authError('该报价数据不在本人可操作范围。',403);
  };
  const claim=async(p,kind,id,table)=>{
    if(typeof id!=='string'||!id.trim()||id.length>200)throw authError('报价标识无效。',400);
    const result=await query(`WITH claimed AS (INSERT INTO calc.quote_name_owner(resource_kind,resource_key,owner_user_id,confirmed_by_name,mapping_source)
      SELECT ${q(kind)},${q(id)},${q(p.userId)},${q(p.displayName)},'SESSION_CREATED'
      WHERE NOT EXISTS(SELECT 1 FROM ${table} old WHERE old.quote_id=${q(id)})
      ON CONFLICT(resource_kind,resource_key) DO UPDATE SET resource_key=EXCLUDED.resource_key
        WHERE calc.quote_name_owner.owner_user_id=EXCLUDED.owner_user_id RETURNING 1)
      SELECT (EXISTS(SELECT 1 FROM claimed) OR ${resourceScopeSql(p,kind,q(id),{write:true})})::text;`);
    if(!result)throw authError('该报价标识不可用于当前人员，请重新创建报价。',403);
  };
  const beforeBody=async(req,input)=>{
    const p=currentQuotePrincipal(),path=new URL(req.url,'http://local').pathname;
    if(!isNamePrincipal(p))return input;
    // Scheme GET/copy authorization is handled by the canonical service.
    if(path==='/api/name-login')return input;
    const ids=new Map();
    const calculating=['/api/quotes/calculate-dual','/api/quotes/calculate-ganged','/api/attachments/snapshot-ganged'].includes(path);
    const visit=(value,nested=false,attachmentMetadata=false)=>{if(!value||typeof value!=='object')return;for(const[k,v]of Object.entries(value)){
      // Popup preview rows carry an ephemeral calculation UUID, not a saved
      // private resource. Remove it from attachment metadata before checking
      // OR persisting a scheme: otherwise it causes false 403s, or could be
      // laundered into an owned-snapshot reference. Cabinet/source IDs remain
      // subject to the unchanged ownership checks below.
      if(k==='quote_line_id'&&attachmentMetadata){delete value[k];continue;}
      if(['quote_line_id','source_quote_line_id','quick_match_source_line_id'].includes(k)&&typeof v==='string')ids.set('QUOTE_LINE:'+v.toLowerCase(),['QUOTE_LINE',v.toLowerCase()]);
      else if(k==='quote_id'&&nested&&!calculating&&typeof v==='string')ids.set('QUOTE_ID:'+v,['QUOTE_ID',v]);
      else if(k==='attachments'&&Array.isArray(v)){for(const row of v)visit(row,true,true);}
      else if(typeof v==='object')visit(v,true,attachmentMetadata&&k==='environment');
    }};
    if(!path.startsWith('/api/quote-schemes'))visit(input);
    else if(input.snapshot)visit(input.snapshot,true);
    for(const[kind,id]of ids.values())await ownReference(p,id,kind);
    if(calculating){
      const rows=path.endsWith('calculate-ganged')?[...(input.cabinets||[]),...(input.attachment?[input.attachment]:[])]:[input];
      for(const row of rows)await claim(p,'QUOTE_ID',row.quote_id,'calc.dual_quote_result');
    }
    if(['/api/quotes/confirm','/api/quotes/confirm-check'].includes(path)&&input.quote_id)
      await claim(p,'QUOTE_DOCUMENT',input.quote_id,'calc.quote_document');
    return input;
  };
  return {beforeBody,ownReference,claim};
}
