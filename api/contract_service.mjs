import {createHash,randomUUID} from 'node:crypto';
import {permissionSql,writePermissionSql} from './quote_scheme_service.mjs';
import {inspectContractTemplate,validateContractMapping,renderContractTemplate,CONTRACT_FIELDS} from './contract_document.mjs';
import {contractQuote} from './contract_quote.mjs';
import {snapshotOrderNature,orderNatureSql} from '../quote_order_nature.mjs';
import {contractCustomer,contractCustomerNameSql} from './contract_customer.mjs';
import {createContractTemplatePolicy,buyerMappingSql,ledgerMappingSql} from './contract_template_policy.mjs';
import {registerContractSql,contractSchemeSql} from './contract_status.mjs';
import {customerProfileView,createCustomerProfileStore,CUSTOMER_PROFILE_FIELDS} from './customer_profile.mjs';
import {createLedgerContractService} from './contract_ledger_service.mjs';
import {displayVersion} from './quote_delivery_document.mjs';
const error=(message,statusCode=400)=>Object.assign(new Error(message),{statusCode});
const documentCall=(fn,...args)=>{try{return fn(...args);}catch(e){e.statusCode=400;throw e;}};
const hash=data=>createHash('sha256').update(data).digest('hex');
const uuid=value=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(value||'')))throw error('记录编号无效');return String(value).toLowerCase();};
const number=value=>{if(!Number.isSafeInteger(Number(value))||Number(value)<1)throw error('版本编号无效');return Number(value);};
const text=(value,label,max=500)=>{if(typeof value!=='string'||/[\x00-\x1f\x7f]/.test(value)||!value.trim()||value.trim().length>max)throw error(label+'不能为空且不能超长');return value.trim().normalize('NFC');};
const all=p=>p.can_view_all_quotes===true||p.canViewAllQuotes===true||p.scope==='ALL';
const stable=value=>JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
export const DEFAULT_SELLER_NAME='浙江京能电力设备有限公司';
export function createContractService({runPsql,sqlUnicodeText:q}){
 const query=async sql=>{const raw=await runPsql(sql);return JSON.parse(String(raw).trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');};
 const templatePolicy=createContractTemplatePolicy({query,q});
 const identity=p=>{if(!p?.userId||String(p.userId).startsWith('shared-client:'))throw error('合同功能需要姓名会话，请先完成姓名登录模块集成并登录；共享连接密钥不能代替人员身份',401);return p;};
 const scope=(p,alias)=>{identity(p);return all(p)?'TRUE':`${alias}.owner_user_id=${q(p.userId)}`;};
 const own=(p,alias)=>{identity(p);return `${alias}.owner_user_id=${q(p.userId)}`;};
 // Templates are shared across named colleagues. Quotes, generated contracts
 // and drafts keep their existing scopes; template maintenance remains own().
 const useTemplate=p=>{identity(p);return 'TRUE';};
 const audit=(p,kind,id,action,detail={})=>`INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name,detail) VALUES(${q(kind)},${q(String(id))},${q(action)},${q(p.userId)},${q(p.displayName)},${q(JSON.stringify(detail))}::jsonb)`;
 const ready=async()=>Boolean((await query("SELECT to_jsonb(to_regclass('calc.contract_generation') IS NOT NULL AND to_regclass('calc.contract_template_version') IS NOT NULL AND to_regprocedure('calc.register_generated_contract(text,uuid,text)') IS NOT NULL)::text;")));
 const requireReady=async()=>{if(!await ready())throw error('合同数据库功能尚未启用，请由发布人员执行新增迁移',503);};
 const source=async(p,no,version)=>{
  identity(p);if(!/^BJ-\d{8}-\d{6}$/.test(String(no||'')))throw error('报价编号无效');number(version);
  const value=await query(`SELECT COALESCE((SELECT jsonb_build_object('scheme_id',s.scheme_id,'scheme_no',s.scheme_no,'version_no',v.version_no,
   'catalog_customer_code',CASE WHEN c.matches=1 THEN c.code END,
   'snapshot_customer_code',v.snapshot_payload#>>'{analysis_customer,customer_code}',
   'snapshot_customer_name',v.snapshot_payload#>>'{analysis_customer,customer_name}',
   'customer_name',${contractCustomerNameSql()},'snapshot',v.snapshot_payload,
   'customer_profile_record',CASE WHEN c.matches=1 THEN c.profile END,'customer_profile_matches',c.matches)
   FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
   LEFT JOIN LATERAL(SELECT count(*) AS matches,min(company_code) AS code,(jsonb_agg(to_jsonb(profile_company))->0) AS profile FROM calc.ordering_company profile_company WHERE btrim(company_name)=${contractCustomerNameSql()}) c ON TRUE
   WHERE s.scheme_no=${q(no)} AND v.version_no=${Number(version)} AND s.status<>'VOID' AND COALESCE(to_jsonb(s)->>'source_kind','QUOTE')='QUOTE' AND ${writePermissionSql({...p,role:'USER',departmentId:null},'s')}),'null'::jsonb)::text;`);
  if(!value)throw error('正式报价不可用或无权用于生成合同',404);
  if(snapshotOrderNature(value.snapshot)!=='EXTERNAL')throw error('仅外部正式报价可用于合同；内部及待分类报价不能进入合同管理。',409);
  const {customer_profile_record,customer_profile_matches,...customer}=contractCustomer(value);
  return {...customer,quote_version:displayVersion(value.snapshot,value.version_no),customer_profile:customerProfileView(customer,customer_profile_record,Number(customer_profile_matches||0))};
 };
 const sourceList=async p=>(await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object('scheme_no',s.scheme_no,'version_no',v.version_no,'quote_version',COALESCE(v.snapshot_payload#>>'{quote_management,current}',v.version_no::text),'order_nature','EXTERNAL','customer_name',${contractCustomerNameSql()},
  'catalog_customer_code',CASE WHEN c.matches=1 THEN c.code END,
  'snapshot_customer_code',v.snapshot_payload#>>'{analysis_customer,customer_code}',
  'snapshot_customer_name',v.snapshot_payload#>>'{analysis_customer,customer_name}',
  'product_summary',s.product_summary) ORDER BY s.updated_at DESC,v.version_no DESC),'[]'::jsonb)::text
  FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
  LEFT JOIN LATERAL(SELECT count(*) AS matches,min(company_code) AS code FROM calc.ordering_company WHERE btrim(company_name)=${contractCustomerNameSql()}) c ON TRUE
  WHERE s.status<>'VOID' AND COALESCE(to_jsonb(s)->>'source_kind','QUOTE')='QUOTE' AND ${orderNatureSql('v.snapshot_payload')}='EXTERNAL' AND ${writePermissionSql({...p,role:'USER',departmentId:null},'s')};`))
    .filter(row=>row.customer_name).map(contractCustomer);
 const template=async(p,id,write=false)=>{
  const result=await query(`SELECT COALESCE((SELECT to_jsonb(t) FROM(SELECT v.template_version_id,v.version_no,v.file_format,v.original_filename,encode(v.file_content,'base64') AS content,v.file_sha256,v.field_mapping,
  g.group_id,g.customer_code,g.customer_name,g.template_name,g.owner_user_id,g.owner_name,g.lock_version,g.enabled,g.is_default
  FROM calc.contract_template_version v JOIN calc.contract_template_group g USING(group_id)
  WHERE v.template_version_id=${number(id)} AND ${write?own(p,'g'):useTemplate(p)}) t),'null'::jsonb)::text;`);
  if(!result)throw error('合同模板不存在或无权访问',404);return result;
 };
 const listRecords=async(p,input={})=>{
  identity(p);await requireReady();const page=Number(input.page??1),search=String(input.search||'').trim();
  if(!Number.isSafeInteger(page)||page<1||page>100000||search.length>200||/[\x00-\x1f]/.test(search))throw error('记录查询条件无效');
  const match=search?` AND (r.customer_name ILIKE '%'||${q(search)}||'%' OR r.customer_contract_no ILIKE '%'||${q(search)}||'%' OR r.record_no ILIKE '%'||${q(search)}||'%' OR g.template_name ILIKE '%'||${q(search)}||'%' OR r.generation_snapshot->>'scheme_no' ILIKE '%'||${q(search)}||'%')`:'';
  const quoteColumns='record_id,record_no,customer_contract_no,customer_code,customer_name,owner_name,owner_user_id,quote_method,file_format,file_sha256,created_at,generation_snapshot,source_version_no,template_version_id';
  const ledgerColumns="record_id,record_no,customer_contract_no,customer_code,customer_name,owner_name,owner_user_id,'LEDGER'::text AS quote_method,file_format,file_sha256,created_at,generation_snapshot,NULL::integer AS source_version_no,template_version_id";
  const hasLedger=await ledger.ready();
  const rowsSql=hasLedger?`(SELECT ${quoteColumns},'QUOTE'::text AS source_kind FROM calc.contract_generation UNION ALL SELECT ${ledgerColumns},'LEDGER'::text AS source_kind FROM calc.ledger_contract_generation)`:'calc.contract_generation';
  const filter=scope(p,'r')+match;
  const items=await query(`SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY created_at DESC,record_id DESC),'[]'::jsonb)::text FROM(SELECT r.record_id,r.record_no,r.customer_contract_no,r.customer_code,r.customer_name,r.owner_name,r.owner_user_id,r.quote_method,r.file_format,r.file_sha256,r.created_at,
   r.generation_snapshot#>>'{quote,total}' AS amount,r.generation_snapshot->>'scheme_no' AS scheme_no,r.source_version_no,r.generation_snapshot->>'source_quote_version' AS source_quote_version,
   v.version_no AS template_version,g.template_name,${hasLedger?'r.source_kind':"'QUOTE'::text AS source_kind"},${own(p,'r')} AS can_write FROM ${rowsSql} r JOIN calc.contract_template_version v USING(template_version_id) JOIN calc.contract_template_group g USING(group_id)
   WHERE ${filter} ORDER BY r.created_at DESC,r.record_id DESC LIMIT 100 OFFSET ${(page-1)*100}) t;`);
  const total=await query(`SELECT count(*)::text FROM ${rowsSql} r JOIN calc.contract_template_version v USING(template_version_id) JOIN calc.contract_template_group g USING(group_id) WHERE ${filter};`);
  return {items,total,page,page_size:100};
 };
 const bootstrap=async p=>{
  identity(p);if(!await ready())return {ready:false,message:'合同功能尚未启用，请由发布人员执行新增迁移',sources:[],templates:[],records:[],drafts:[]};
  const sources=await sourceList(p);
  const templates=await query(`SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY customer_name,template_name),'[]'::jsonb)::text FROM(SELECT g.*,v.template_version_id,v.version_no,v.file_format,v.original_filename,(v.field_mapping IS NOT NULL) AS configured,${buyerMappingSql('v')} AS buyer_configured,${ledgerMappingSql('v')} AS ledger_compatible,${own(p,'g')} AS can_write,${useTemplate(p)} AS can_use
   FROM calc.contract_template_group g JOIN LATERAL(SELECT * FROM calc.contract_template_version v WHERE v.group_id=g.group_id ORDER BY version_no DESC LIMIT 1) v ON TRUE WHERE ${useTemplate(p)})t;`);
  const recordPage=await listRecords(p);const records=recordPage.items;
  const drafts=await query(`SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY updated_at DESC),'[]'::jsonb)::text FROM(SELECT draft_id,input_payload,lock_version,updated_at FROM calc.contract_generation_draft d WHERE ${own(p,'d')} ORDER BY updated_at DESC LIMIT 100)t;`);
  return {ready:true,sources,templates,records,records_total:recordPage.total,drafts,fields:CONTRACT_FIELDS};
 };
 const quote=async(p,input)=>{const s=await source(p,input.scheme_no,input.version_no);return {...s,snapshot:undefined,quote:documentCall(contractQuote,s.snapshot,input.method)};};
 const storeTemplateForCustomer=async(p,input,s)=>{
  identity(p);await requireReady();
  if(input.customer_code!==s.customer_code)throw error('模板客户必须与所选正式报价一致');
  const name=text(input.template_name,'模板名称',120),filename=text(input.filename,'文件名',200),format=String(input.format||'').toLowerCase();
  if(!filename.toLowerCase().endsWith('.'+format)||typeof input.content!=='string'||input.content.length>12*1024*1024||!/^[A-Za-z0-9+/]*={0,2}$/.test(input.content))throw error('模板文件格式或内容无效');
  const bytes=Buffer.from(input.content,'base64'),inspection=documentCall(inspectContractTemplate,bytes,format),groupId=input.group_id?uuid(input.group_id):randomUUID();
  if(!input.group_id&&await query(`SELECT to_jsonb(EXISTS(SELECT 1 FROM calc.contract_template_group g WHERE customer_code=${q(s.customer_code)} AND template_name=${q(name)} AND ${own(p,'g')}))::text;`))throw error('该客户已有同名模板，请选择上传新版本或使用其他模板名称',409);
  let result;
  if(input.group_id){
   const expected=number(input.expected_version);
   result=await query(`WITH owned AS(UPDATE calc.contract_template_group g SET lock_version=lock_version+1 WHERE group_id=${q(groupId)}::uuid AND customer_code=${q(s.customer_code)} AND lock_version=${expected} AND ${own(p,'g')} RETURNING *),
    added AS(INSERT INTO calc.contract_template_version(group_id,version_no,file_format,original_filename,file_content,file_sha256)
    SELECT group_id,(SELECT COALESCE(max(version_no),0)+1 FROM calc.contract_template_version WHERE group_id=o.group_id),${q(format)},${q(filename)},decode('${bytes.toString('hex')}','hex'),${q(hash(bytes))} FROM owned o RETURNING *),
    audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name) SELECT 'TEMPLATE',template_version_id::text,'UPLOADED',${q(p.userId)},${q(p.displayName)} FROM added)
    SELECT COALESCE((SELECT jsonb_build_object('template_version_id',template_version_id,'version_no',version_no,'group_id',group_id) FROM added),'null'::jsonb)::text;`);
  }else result=await query(`WITH made AS(INSERT INTO calc.contract_template_group(group_id,customer_code,customer_name,template_name,owner_user_id,owner_name)
    VALUES(${q(groupId)}::uuid,${q(s.customer_code)},${q(s.customer_name)},${q(name)},${q(p.userId)},${q(p.displayName)}) RETURNING *),
    added AS(INSERT INTO calc.contract_template_version(group_id,version_no,file_format,original_filename,file_content,file_sha256)
    SELECT group_id,1,${q(format)},${q(filename)},decode('${bytes.toString('hex')}','hex'),${q(hash(bytes))} FROM made RETURNING *),
    audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name) SELECT 'TEMPLATE',template_version_id::text,'UPLOADED',${q(p.userId)},${q(p.displayName)} FROM added)
    SELECT (SELECT jsonb_build_object('template_version_id',template_version_id,'version_no',version_no,'group_id',group_id) FROM added)::text;`);
  if(!result)throw error('模板版本已变化，请刷新后重试',409);
  return {...result,inspection};
 };
 const upload=async(p,input)=>{const s=await source(p,input.scheme_no,input.version_no);return storeTemplateForCustomer(p,input,s);};
 const inspect=async(p,id)=>{await requireReady();const t=await template(p,id);return {template:{...t,content:undefined},inspection:documentCall(inspectContractTemplate,Buffer.from(t.content,'base64'),t.file_format)};};
 const versions=async(p,id)=>{await requireReady();const t=await template(p,id);return {items:await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object('version_no',version_no,'original_filename',original_filename,'configured',field_mapping IS NOT NULL,'created_at',created_at) ORDER BY version_no DESC),'[]'::jsonb)::text FROM calc.contract_template_version WHERE group_id=${q(t.group_id)}::uuid;`)};};
 const configure=async(p,id,input)=>{
  await requireReady();const t=await template(p,id,true);const mapping=documentCall(validateContractMapping,Buffer.from(t.content,'base64'),t.file_format,input.mapping),expected=number(input.expected_version);
  const result=await query(`WITH owned AS(UPDATE calc.contract_template_group g SET lock_version=lock_version+1 WHERE group_id=${q(t.group_id)}::uuid AND lock_version=${expected} AND ${own(p,'g')}
   AND (SELECT max(template_version_id) FROM calc.contract_template_version WHERE group_id=g.group_id)=${number(id)} RETURNING *),
   added AS(INSERT INTO calc.contract_template_version(group_id,version_no,file_format,original_filename,file_content,file_sha256,field_mapping)
   SELECT v.group_id,v.version_no+1,v.file_format,v.original_filename,v.file_content,v.file_sha256,${q(JSON.stringify(mapping))}::jsonb FROM calc.contract_template_version v JOIN owned o USING(group_id) WHERE v.template_version_id=${number(id)} RETURNING *),
   audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name,detail) SELECT 'TEMPLATE',template_version_id::text,'CONFIGURED',${q(p.userId)},${q(p.displayName)},${q(JSON.stringify({mapping}))}::jsonb FROM added)
   SELECT COALESCE((SELECT jsonb_build_object('configured',TRUE,'template_version_id',template_version_id,'version_no',version_no) FROM added),'null'::jsonb)::text;`);
  if(!result)throw error('模板已更新，请重新加载后配置',409);return result;
 };
 const setTemplate=async(p,id,input)=>{
  await requireReady();
  const t=await template(p,id,true);const enabled=input.enabled===true,isDefault=input.is_default===true,expected=number(input.expected_version);
  const result=await query(`WITH lock AS(SELECT pg_advisory_xact_lock(hashtext(${q(p.userId+'|'+t.customer_code)}))),owned AS(UPDATE calc.contract_template_group g SET enabled=${enabled},is_default=${isDefault},lock_version=lock_version+1 FROM lock
   WHERE group_id=${q(t.group_id)}::uuid AND lock_version=${expected} AND ${own(p,'g')} RETURNING g.*),
   cleared AS(UPDATE calc.contract_template_group g SET is_default=FALSE,lock_version=g.lock_version+1 FROM owned o WHERE ${isDefault} AND g.owner_user_id=o.owner_user_id AND g.customer_code=o.customer_code AND g.group_id<>o.group_id),
   audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name) SELECT 'TEMPLATE',group_id::text,'SETTINGS',${q(p.userId)},${q(p.displayName)} FROM owned)
   SELECT jsonb_build_object('saved',EXISTS(SELECT 1 FROM owned))::text;`);
  if(!result.saved)throw error('模板设置已变化，请刷新后重试',409);return result;
 };
 const cleanInput=input=>{const data={scheme_no:String(input.scheme_no||''),version_no:number(input.version_no),template_version_id:number(input.template_version_id),method:String(input.method||''),fields:{}};
  if(!['QUICK','FORMULA'].includes(data.method))throw error('请选择采用的报价方式');
  if(!input.fields||typeof input.fields!=='object'||Array.isArray(input.fields))throw error('请补充合同字段');
  for(const [key,value] of Object.entries(input.fields)){if(Object.keys(CONTRACT_FIELDS).includes(key)&&!['contract_no','seller_name','sign_date','delivery_date','seller_address',...Object.keys(CUSTOMER_PROFILE_FIELDS)].includes(key))continue;
   if(!Object.keys(CONTRACT_FIELDS).includes(key)&&!/^custom:[^\x00-\x1f{}]{1,80}$/.test(key))throw error('合同字段无效');
   if(typeof value!=='string'||value.length>5000||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value))throw error('合同字段内容无效');data.fields[key]=value.trim();}
  return data;
 };
 const saveDraft=async(p,input)=>{identity(p);await requireReady();const data=cleanInput(input),s=await source(p,data.scheme_no,data.version_no),t=await template(p,data.template_version_id);
  await templatePolicy.validate(s,t);
  const id=input.draft_id?uuid(input.draft_id):randomUUID(),expected=Number(input.expected_version||0);
  const result=await query(`WITH saved AS(INSERT INTO calc.contract_generation_draft(draft_id,owner_user_id,owner_name,input_payload)
   SELECT ${q(id)}::uuid,${q(p.userId)},${q(p.displayName)},${q(JSON.stringify(data))}::jsonb WHERE ${expected}=0
   ON CONFLICT(draft_id) DO NOTHING RETURNING *),changed AS(UPDATE calc.contract_generation_draft d SET input_payload=${q(JSON.stringify(data))}::jsonb,lock_version=lock_version+1,updated_at=now() WHERE draft_id=${q(id)}::uuid AND lock_version=${Number.isSafeInteger(expected)?expected:-1} AND ${own(p,'d')} RETURNING *)
   SELECT COALESCE((SELECT jsonb_build_object('draft_id',draft_id,'lock_version',lock_version) FROM(SELECT * FROM saved UNION ALL SELECT * FROM changed)t),'null'::jsonb)::text;`);
  if(!result)throw error('草稿已变化，请重新打开后保存',409);return result;
 };
 const record=async(p,id,includeFile=false)=>{identity(p);const result=await query(`SELECT COALESCE((SELECT to_jsonb(r) FROM(SELECT record_id,record_no,generation_snapshot,file_format,file_sha256,${includeFile?"encode(file_content,'base64')":'NULL::text'} AS content,owner_user_id,${contractSchemeSql('QUOTE','r.record_id',q)} AS scheme FROM calc.contract_generation r WHERE record_id=${q(uuid(id))}::uuid AND ${includeFile?own(p,'r'):scope(p,'r')})r),'null'::jsonb)::text;`);if(!result){if(await ledger.ready())return ledger.record(p,id,includeFile);throw error('生成记录不存在或无权查看',404);}return result;};
 const generate=async(p,input)=>{
  identity(p);await requireReady();const data=cleanInput(input),requestId=uuid(input.request_id),digest=hash(stable(data));
  const prior=await query(`SELECT COALESCE((SELECT jsonb_build_object('record_id',record_id,'input_sha256',input_sha256) FROM calc.contract_generation r WHERE request_id=${q(requestId)}::uuid AND ${own(p,'r')}),'null'::jsonb)::text;`);
  if(prior){if(prior.input_sha256!==digest)throw error('本次生成编号已对应其他内容，请新建生成操作',409);const r=await record(p,prior.record_id);return {...r,content:undefined,reused:true};}
  const s=await source(p,data.scheme_no,data.version_no),t=await template(p,data.template_version_id);
  const borrowed=await templatePolicy.validate(s,t);
  const selected=documentCall(contractQuote,s.snapshot,data.method),values={...(s.customer_profile?.fields||{}),...data.fields,
    contract_no:data.fields.contract_no??'',seller_name:data.fields.seller_name??DEFAULT_SELLER_NAME,
    buyer_name:s.customer_name,total_amount:selected.total,total_upper:selected.total_upper,source_scheme_no:s.scheme_no,source_version:String(s.quote_version),quote_method:data.method==='QUICK'?'快速报价':'公式报价'};
  if(values.contract_no)text(values.contract_no,'客户合同编号',200);
  for(const key of ['sign_date','delivery_date'])if(values[key]&&(!/^\d{4}-\d{2}-\d{2}$/.test(values[key])||Number.isNaN(Date.parse(values[key]))||new Date(values[key]).toISOString().slice(0,10)!==values[key]))throw error('合同日期格式无效');
  const bytes=documentCall(renderContractTemplate,Buffer.from(t.content,'base64'),t.file_format,t.field_mapping,values,selected.items);
  if(bytes.length>16*1024*1024)throw error('生成合同超过16MB，请简化模板中的图片');
  const id=randomUUID(),snapshot={scheme_no:s.scheme_no,source_version:s.version_no,source_quote_version:s.quote_version,order_nature:'EXTERNAL',template_name:t.template_name,template_version:t.version_no,template_sha256:t.file_sha256,template_customer_name:t.customer_name,template_borrowed:borrowed,mapping:t.field_mapping,quote:selected,fields:values,method:data.method,customer_profile_version:s.customer_profile?.version??0};
  const inserted=await query(`WITH allowed AS(SELECT s.scheme_id FROM calc.quote_scheme s JOIN calc.contract_template_group g ON g.group_id=${q(t.group_id)}::uuid WHERE s.scheme_id=${Number(s.scheme_id)} AND s.status<>'VOID' AND g.enabled AND ${useTemplate(p)} AND ${writePermissionSql({...p,role:'USER',departmentId:null},'s')}
    AND ${templatePolicy.allowedSql(s)} AND EXISTS(SELECT 1 FROM calc.quote_scheme_version v WHERE v.scheme_id=s.scheme_id AND v.version_no=${s.version_no} AND ${orderNatureSql('v.snapshot_payload')}='EXTERNAL')),
   made AS(INSERT INTO calc.contract_generation(record_id,record_no,request_id,input_sha256,owner_user_id,owner_name,customer_code,customer_name,customer_contract_no,source_scheme_id,source_version_no,template_version_id,quote_method,generation_snapshot,file_format,file_content,file_sha256)
   SELECT ${q(id)}::uuid,'HT-'||to_char(now() AT TIME ZONE 'Asia/Shanghai','YYYYMMDD')||'-'||lpad(nextval('calc.contract_record_number')::text,6,'0'),${q(requestId)}::uuid,${q(digest)},${q(p.userId)},${q(p.displayName)},${q(s.customer_code)},${q(s.customer_name)},${q(values.contract_no)},scheme_id,${s.version_no},${number(t.template_version_id)},${q(data.method)},${q(JSON.stringify(snapshot))}::jsonb,${q(t.file_format)},decode('${bytes.toString('hex')}','hex'),${q(hash(bytes))} FROM allowed
   ON CONFLICT(owner_user_id,request_id) DO NOTHING RETURNING *),
   audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name,detail) SELECT 'GENERATION',record_id::text,'GENERATED',${q(p.userId)},${q(p.displayName)},jsonb_build_object('source_scheme_no',${q(s.scheme_no)},'source_version',${s.version_no}) FROM made)
   , registered AS(SELECT m.record_id,${registerContractSql('QUOTE','m',p,q)} AS scheme FROM made m)
   SELECT COALESCE((SELECT jsonb_build_object('record_id',record_id,'record_no',record_no,'file_sha256',file_sha256,'file_format',file_format,'generation_snapshot',generation_snapshot,'scheme',scheme) FROM made JOIN registered USING(record_id)),'null'::jsonb)::text;`);
  if(!inserted){const raced=await query(`SELECT COALESCE((SELECT jsonb_build_object('record_id',record_id,'input_sha256',input_sha256) FROM calc.contract_generation r WHERE request_id=${q(requestId)}::uuid AND ${own(p,'r')}),'null'::jsonb)::text;`);if(raced?.input_sha256===digest){const r=await record(p,raced.record_id);return {...r,content:undefined,reused:true};}throw error('正式报价或模板状态已变化，请重新核对',409);}
  return inserted;
 };
 const download=async(p,id)=>{await requireReady();const r=await record(p,id,true);await query(`${audit(p,r.source_kind==='LEDGER'?'LEDGER_GENERATION':'GENERATION',id,'DOWNLOADED')}; SELECT 'true'::jsonb::text;`);return {filename:r.record_no+'.'+r.file_format,format:r.file_format,sha256:r.file_sha256,bytes:Buffer.from(r.content,'base64')};};
 const customerProfiles=createCustomerProfileStore({query,q,source});
 const ledger=createLedgerContractService({query,q,identity,scope,own,loadTemplate:template,storeTemplate:storeTemplateForCustomer,configureTemplate:configure,defaultSellerName:DEFAULT_SELLER_NAME});
 return {bootstrap,listRecords,quote,upload,inspect,versions,configure,setTemplate,saveDraft,generate,record,download,ledger,
  customerProfile:customerProfiles.get,saveCustomerProfile:customerProfiles.save};
}
