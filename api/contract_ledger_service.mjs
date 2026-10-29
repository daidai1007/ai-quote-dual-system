import {createHash,randomUUID} from 'node:crypto';
import {cleanLedgerInput,ledgerDocuments,ledgerCustomer,LEDGER_CUSTOMERS,stableLedgerValue} from './contract_ledger_data.mjs';
import {renderContractTemplate} from './contract_document.mjs';
import {contractCustomer} from './contract_customer.mjs';
import {customerProfileView} from './customer_profile.mjs';
const fail=(message,statusCode=400)=>{throw Object.assign(new Error(message),{statusCode});};
const uuid=value=>{if(!/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(String(value||'')))fail('台账合同记录编号无效');return String(value).toLowerCase();};
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');

export function createLedgerContractService({query,q,identity,scope,own,loadTemplate,storeTemplate,configureTemplate,defaultSellerName}){
 const ready=async()=>Boolean(await query("SELECT to_jsonb(to_regclass('calc.ledger_contract_generation') IS NOT NULL AND to_regclass('calc.ledger_contract_draft') IS NOT NULL)::text;"));
 const requireReady=async()=>{if(!await ready())fail('台账合同功能尚未启用，请由发布人员执行配套迁移并更新 API。',503);};
 const customer=async(p,key)=>{
  identity(p);const entry=ledgerCustomer(key);
  const found=await query(`SELECT jsonb_build_object('matches',count(*),'code',min(company_code),'profile',jsonb_agg(to_jsonb(c))->0)::text FROM calc.ordering_company c WHERE btrim(company_name)=${q(entry.name)};`);
  const value=contractCustomer({customer_name:entry.name,catalog_customer_code:Number(found?.matches)===1?found.code:null});
  return {...value,customer_key:key,customer_profile:customerProfileView(value,Number(found?.matches)===1?found.profile:null,Number(found?.matches||0))};
 };
 const bootstrap=async p=>{
  identity(p);if(!await ready())return {ready:false,customers:LEDGER_CUSTOMERS,templates:[],drafts:[],message:'台账合同功能尚未启用，请由发布人员执行新增迁移并更新 API。'};
  const names=Object.values(LEDGER_CUSTOMERS).map(c=>q(c.name)).join(',');
  const templates=await query(`SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY customer_name,template_name,version_no DESC),'[]'::jsonb)::text FROM(
   SELECT g.*,v.template_version_id,v.version_no,v.file_format,v.original_filename,(v.field_mapping IS NOT NULL) AS configured,${own(p,'g')} AS can_write,TRUE AS can_use
   FROM calc.contract_template_group g JOIN calc.contract_template_version v ON v.group_id=g.group_id
   WHERE btrim(g.customer_name) IN (${names}))t;`);
  const drafts=await query(`SELECT COALESCE(jsonb_agg(to_jsonb(d) ORDER BY updated_at DESC),'[]'::jsonb)::text FROM(
   SELECT draft_id,customer_name,lock_version,updated_at,input_payload#>>'{source,filename}' AS filename,jsonb_array_length(input_payload->'records') AS item_count
   FROM calc.ledger_contract_draft d WHERE ${own(p,'d')} ORDER BY updated_at DESC LIMIT 100)d;`);
  return {ready:true,customers:LEDGER_CUSTOMERS,templates,drafts};
 };
 const validateTemplate=async(p,data)=>{
  const c=await customer(p,data.customer_key),t=await loadTemplate(p,data.template_version_id);
  if(!t.enabled||!t.field_mapping)fail('客户模板尚未配置或已停用');
  if(!['name','specification','quantity','unit','unit_price','total','remark'].every(key=>Object.hasOwn(t.field_mapping.items?.columns||{},key)))fail('台账合同模板须配置名称、规格、数量、单位、单价、金额和备注，避免输出遗漏');
  if(String(t.customer_name).trim().normalize('NFC')!==c.customer_name)fail('合同模板与台账客户不一致');
  return {customer:c,template:t};
 };
 const upload=async(p,input)=>{
  identity(p);await requireReady();const c=await customer(p,input.customer_key);
  const result=await storeTemplate(p,{...input,customer_code:c.customer_code},c);
  const mapping=result.inspection?.suggested;
  if(!mapping?.items||!['name','specification','quantity','unit','unit_price','total','remark'].every(key=>Object.hasOwn(mapping.items.columns||{},key))||!mapping.fields?.some(f=>f.source==='buyer_name')||!mapping.fields?.some(f=>f.source==='total_amount'))return {...result,auto_configured:false};
  const t=await loadTemplate(p,result.template_version_id,true);
  const configured=await configureTemplate(p,result.template_version_id,{mapping,expected_version:t.lock_version});
  return {...result,...configured,auto_configured:true};
 };
 const saveDraft=async(p,input)=>{
  identity(p);await requireReady();const data=cleanLedgerInput(input);ledgerDocuments(data,{requireFields:false});
  const {customer:c}=await validateTemplate(p,data),id=input.draft_id?uuid(input.draft_id):randomUUID(),expected=Number(input.expected_version??0);
  if(!Number.isSafeInteger(expected)||expected<0)fail('草稿版本无效');
  const payload=q(JSON.stringify(data));
  const result=await query(`WITH made AS(INSERT INTO calc.ledger_contract_draft(draft_id,owner_user_id,owner_name,customer_name,input_payload)
    SELECT ${q(id)}::uuid,${q(p.userId)},${q(p.displayName)},${q(c.customer_name)},${payload}::jsonb WHERE ${expected}=0
    ON CONFLICT(draft_id) DO NOTHING RETURNING *), changed AS(
    UPDATE calc.ledger_contract_draft d SET input_payload=${payload}::jsonb,customer_name=${q(c.customer_name)},lock_version=lock_version+1,updated_at=now()
    WHERE draft_id=${q(id)}::uuid AND lock_version=${expected} AND ${own(p,'d')} RETURNING *)
    SELECT COALESCE((SELECT jsonb_build_object('draft_id',draft_id,'lock_version',lock_version) FROM(SELECT * FROM made UNION ALL SELECT * FROM changed)t),'null'::jsonb)::text;`);
  if(!result)fail('草稿已变化或无权保存，请重新打开后核对',409);return result;
 };
 const draft=async(p,id)=>{
  identity(p);await requireReady();const result=await query(`SELECT COALESCE((SELECT to_jsonb(d) FROM calc.ledger_contract_draft d WHERE draft_id=${q(uuid(id))}::uuid AND ${own(p,'d')}),'null'::jsonb)::text;`);
  if(!result)fail('台账合同草稿不存在或无权查看',404);return result;
 };
 const record=async(p,id,includeFile=false)=>{
  identity(p);await requireReady();const result=await query(`SELECT COALESCE((SELECT jsonb_build_object('record_id',record_id,'record_no',record_no,
    'generation_snapshot',generation_snapshot,'file_format',file_format,'file_sha256',file_sha256,'owner_user_id',owner_user_id,'source_kind','LEDGER',
    'content',${includeFile?"encode(file_content,'base64')":'NULL::text'}) FROM calc.ledger_contract_generation r
    WHERE record_id=${q(uuid(id))}::uuid AND ${includeFile?own(p,'r'):scope(p,'r')}),'null'::jsonb)::text;`);
  if(!result)fail('台账合同记录不存在或无权查看',404);return result;
 };
 const generate=async(p,input)=>{
  identity(p);await requireReady();const data=cleanLedgerInput(input),requestId=uuid(input.request_id),digest=hash(stableLedgerValue(data));
  const prior=await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object('record_id',record_id,'input_sha256',input_sha256) ORDER BY record_no),'[]'::jsonb)::text FROM calc.ledger_contract_generation r WHERE request_id=${q(requestId)}::uuid AND ${own(p,'r')};`);
  if(prior.length){if(prior.some(r=>r.input_sha256!==digest))fail('本次生成编号已对应其他内容，请重新发起生成',409);return {records:await Promise.all(prior.map(r=>record(p,r.record_id))),reused:true};}
  const documents=ledgerDocuments(data),{customer:c,template:t}=await validateTemplate(p,data);
  const prepared=documents.map(document=>{
   const fields={...(c.customer_profile?.fields||{}),...data.fields,
    buyer_name:c.customer_name,seller_name:data.fields.seller_name||defaultSellerName,
    contract_no:document.contract_no,sign_date:document.sign_date,delivery_date:document.delivery_date,
    total_amount:document.quote.total,total_upper:document.quote.total_upper,source_scheme_no:'',source_version:'',quote_method:'台账合同'};
   let bytes;try{bytes=renderContractTemplate(Buffer.from(t.content,'base64'),t.file_format,t.field_mapping,fields,document.quote.items);}catch(error){error.statusCode=400;throw error;}
   if(bytes.length>16*1024*1024)fail('生成合同超过16MB，请简化模板');
   const originalRows=data.records.filter(r=>document.source_records.some(s=>s.record_id===r.record_id));
   return {id:randomUUID(),document_key:document.key,fields,bytes,sha256:hash(bytes),snapshot:{schema:1,source_kind:'LEDGER',order_nature:'EXTERNAL',
    customer_key:data.customer_key,customer_name:c.customer_name,ledger_source:data.source,source_records:document.source_records,
    original_records:originalRows,fields,quote:document.quote,method:'LEDGER',
    template_name:t.template_name,template_version:t.version_no,template_version_id:t.template_version_id,template_sha256:t.file_sha256,
    mapping:t.field_mapping,customer_profile_version:c.customer_profile?.version??0}};
  });
  if(prepared.reduce((a,r)=>a+r.bytes.length,0)>64*1024*1024)fail('本批合同文件总量超过64MB，请分批生成');
  const values=prepared.map(row=>`(${q(row.id)}::uuid,${q(row.document_key)},${q(row.fields.contract_no)},${q(JSON.stringify(row.snapshot))}::jsonb,decode('${row.bytes.toString('hex')}','hex'),${q(row.sha256)})`).join(',');
  const result=await query(`BEGIN;SELECT pg_advisory_xact_lock(hashtext(${q(p.userId+'|ledger|'+requestId)}));
   WITH inputs(record_id,document_key,contract_no,snapshot,content,file_hash) AS(VALUES ${values}),
   allowed AS(SELECT g.group_id FROM calc.contract_template_group g WHERE g.group_id=${q(t.group_id)}::uuid AND g.enabled
    AND btrim(g.customer_name)=${q(c.customer_name)}),
   existing AS(SELECT * FROM calc.ledger_contract_generation r WHERE request_id=${q(requestId)}::uuid AND ${own(p,'r')}),
   made AS(INSERT INTO calc.ledger_contract_generation(record_id,record_no,request_id,document_key,input_sha256,owner_user_id,owner_name,
    customer_code,customer_name,customer_contract_no,template_version_id,generation_snapshot,file_format,file_content,file_sha256)
    SELECT i.record_id,'HT-'||to_char(now() AT TIME ZONE 'Asia/Shanghai','YYYYMMDD')||'-'||lpad(nextval('calc.contract_record_number')::text,6,'0'),
     ${q(requestId)}::uuid,i.document_key,${q(digest)},${q(p.userId)},${q(p.displayName)},${q(t.customer_code)},${q(c.customer_name)},i.contract_no,
     ${Number(t.template_version_id)},i.snapshot,${q(t.file_format)},i.content,i.file_hash FROM inputs i
     WHERE EXISTS(SELECT 1 FROM allowed) AND NOT EXISTS(SELECT 1 FROM existing)
     ON CONFLICT(owner_user_id,request_id,document_key) DO NOTHING RETURNING *),
   audited AS(INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name,detail)
    SELECT 'LEDGER_GENERATION',record_id::text,'GENERATED',${q(p.userId)},${q(p.displayName)},jsonb_build_object('template_version',${Number(t.version_no)}) FROM made),
   selected AS(SELECT * FROM made UNION ALL SELECT * FROM existing WHERE input_sha256=${q(digest)})
   SELECT jsonb_build_object('records',COALESCE(jsonb_agg(jsonb_build_object('record_id',record_id,'record_no',record_no,'file_format',file_format,
    'file_sha256',file_sha256,'generation_snapshot',generation_snapshot,'owner_user_id',owner_user_id,'source_kind','LEDGER') ORDER BY record_no),'[]'::jsonb),
    'count',count(*))::text FROM selected;COMMIT;`);
  if(result.count!==prepared.length)fail('模板状态或本次生成内容已变化，请重新核对',409);
  return {records:result.records,reused:false};
 };
 return {ready,bootstrap,upload,saveDraft,draft,generate,record};
}
