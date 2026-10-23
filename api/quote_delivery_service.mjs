import {createHash,randomUUID} from 'node:crypto';
import {isNamePrincipal,quoteScopeSql,currentQuotePrincipal,q} from './quote_access_scope.mjs';
import {normalizeName,nameUserId,ALL_QUOTE_NAMES} from './name_login_service.mjs';
import {deliveryDocument,deliveryWorkbook,displayVersion} from './quote_delivery_document.mjs';

const error=(message,statusCode=400)=>Object.assign(Error(message),{statusCode});
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const uuid=value=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value||''))throw error('请求标识无效。');return value.toLowerCase();};
const scheme=value=>{if(!/^BJ-\d{8}-\d{6}$/.test(value||''))throw error('报价编号无效。');return value;};
const version=value=>{if(!Number.isSafeInteger(Number(value))||Number(value)<1)throw error('请选择正式报价版本。');return Number(value);};
const principal=value=>{const p=currentQuotePrincipal()||value;if(!isNamePrincipal(p))throw error('姓名会话已失效，请重新登录。',401);return p;};

export function createQuoteDeliveryService({runPsql,activePeople=()=>[]}){
  const query=async sql=>JSON.parse(String(await runPsql(sql)).trim().split(/\r?\n/).at(-1)||'null');
  const ready=async()=>{if(!await query("SELECT to_jsonb(to_regclass('calc.quote_delivery_batch') IS NOT NULL AND to_regclass('calc.quote_delivery_recipient') IS NOT NULL AND to_regclass('calc.quote_delivery_output') IS NOT NULL)::text;"))throw error('同事发送功能尚未开通，请联系管理员完成配套数据库升级。',503);};
  const colleagues=async p=>{
    p=principal(p);await ready();
    const stored=await query(`SELECT COALESCE(jsonb_agg(name),'[]'::jsonb)::text FROM (
      SELECT creator_name_entered AS name FROM calc.quote_scheme
      UNION SELECT recipient_name FROM calc.quote_delivery_recipient
      UNION SELECT sender_name FROM calc.quote_delivery_batch) names WHERE btrim(name)<>'';`);
    const names=[...new Set([...ALL_QUOTE_NAMES,...activePeople().map(x=>x.displayName),...stored])];
    return {items:names.map(normalizeName).filter(n=>nameUserId(n)!==p.userId).sort((a,b)=>a.localeCompare(b,'zh-CN')).map(name=>({name,user_id:nameUserId(name)}))};
  };
  const versions=async(p,no)=>{
    p=principal(p);await ready();scheme(no);
    const rows=await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object('source_version_no',v.version_no,
      'snapshot',v.snapshot_payload,'quote_date',to_char(v.quoted_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD'),'quoted_at',v.quoted_at) ORDER BY v.version_no DESC),'[]'::jsonb)::text
      FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
      WHERE s.scheme_no=${q(no)} AND s.status<>'VOID' AND ${quoteScopeSql(p,'s',true)};`);
    const items=[];
    for(const row of rows){try{const document=deliveryDocument(row.snapshot,no,row.source_version_no,row.quote_date);items.push({source_version_no:row.source_version_no,quote_version:document.quote_version,quoted_at:row.quoted_at,document});}catch{}}
    return {items};
  };
  const send=async(p,input)=>{
    p=principal(p);await ready();const id=uuid(input.request_id),no=scheme(input.scheme_no),vn=version(input.source_version_no),qn=version(input.quote_version);
    if(!Array.isArray(input.recipient_names)||!input.recipient_names.length||input.recipient_names.length>30)throw error('请选择1至30位接收同事。');
    const names=[...new Set(input.recipient_names.map(normalizeName))].sort();
    if(names.some(n=>nameUserId(n)===p.userId))throw error('不能发送给当前登录人。');
    if(typeof input.note!=='string'||[...input.note].length>200||/[\p{Cc}\p{Cf}]/u.test(input.note.replace(/[\r\n\t]/g,'')))throw error('附言最多200字，不支持控制字符。');
    const note=input.note.trim(),requestHash=hash({scheme_no:no,source_version_no:vn,quote_version:qn,names,note});
    // A committed request can be retried even if a later revision/void occurred.
    const previous=await query(`SELECT COALESCE((SELECT jsonb_build_object('sender',sender_user_id,'hash',request_sha256) FROM calc.quote_delivery_batch WHERE batch_id=${q(id)}::uuid),'null'::jsonb)::text;`);
    if(previous){if(previous.sender!==p.userId||previous.hash!==requestHash)throw error('发送请求编号已使用，请刷新后重试。',409);return {sent:true,batch_id:id,duplicate:true};}
    const source=await query(`SELECT COALESCE((SELECT jsonb_build_object('scheme_id',s.scheme_id,'snapshot',v.snapshot_payload,'quote_date',to_char(v.quoted_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD'))
      FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
      WHERE s.scheme_no=${q(no)} AND s.status<>'VOID' AND v.version_no=${vn} AND ${quoteScopeSql(p,'s',true)}),'null'::jsonb)::text;`);
    if(!source)throw error('正式版本不存在或无发送权限，请先完成正式打印/导出登记。',403);
    if(displayVersion(source.snapshot,vn)!==qn)throw error('选定报价版本不匹配，请重新打开后发送。',409);
    let document;try{document=deliveryDocument(source.snapshot,no,vn,source.quote_date);}catch(e){throw error(e.message,409);}
    const documentHash=hash(document);
    const recipients=names.map(name=>`(${q(randomUUID())}::uuid,${q(nameUserId(name))},${q(name)})`).join(',');
    await query(`WITH source AS(SELECT s.scheme_id FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
      WHERE s.scheme_no=${q(no)} AND v.version_no=${vn} AND s.status<>'VOID' AND ${quoteScopeSql(p,'s',true)}
        AND v.snapshot_payload=${q(JSON.stringify(source.snapshot))}::jsonb FOR SHARE OF s),
      added AS(INSERT INTO calc.quote_delivery_batch(batch_id,sender_user_id,sender_name,scheme_id,source_version_no,quote_version,note,request_sha256,document_sha256,document_payload)
        SELECT ${q(id)}::uuid,${q(p.userId)},${q(p.displayName)},scheme_id,${vn},${qn},${q(note)},${q(requestHash)},${q(documentHash)},${q(JSON.stringify(document))}::jsonb FROM source ON CONFLICT DO NOTHING RETURNING batch_id),
      recipients AS(INSERT INTO calc.quote_delivery_recipient(delivery_id,batch_id,recipient_user_id,recipient_name)
        SELECT r.id,batch_id,r.uid,r.name FROM added CROSS JOIN (VALUES ${recipients}) r(id,uid,name) RETURNING 1)
      SELECT count(*)::text FROM recipients;`);
    const committed=await query(`SELECT COALESCE((SELECT jsonb_build_object('sender',sender_user_id,'hash',request_sha256) FROM calc.quote_delivery_batch WHERE batch_id=${q(id)}::uuid),'null'::jsonb)::text;`);
    if(!committed||committed.sender!==p.userId||committed.hash!==requestHash)throw error('发送未完成，报价可能已变化；请刷新后重试。',409);
    return {sent:true,batch_id:id,recipient_count:names.length};
  };
  const list=async(p,filters={})=>{
    p=principal(p);await ready();const page=Math.max(1,Math.min(100000,Number(filters.page)||1));
    const records=filters.mode==='sent';
    const where=records?(filters.scheme_no?`s.scheme_no=${q(scheme(filters.scheme_no))} AND ${quoteScopeSql(p,'s',true)}`:`b.sender_user_id=${q(p.userId)}`):`r.recipient_user_id=${q(p.userId)}`;
    return query(`WITH entries AS(SELECT r.delivery_id,r.recipient_name,r.read_at,b.batch_id,b.sender_name,b.created_at,b.note,b.source_version_no,b.quote_version,
      b.document_payload->>'scheme_no' AS scheme_no,b.document_payload->>'customer' AS customer,b.document_payload->>'order_nature' AS order_nature,
      b.document_payload->'total' AS total,count(*) OVER() AS total_count
      FROM calc.quote_delivery_recipient r JOIN calc.quote_delivery_batch b USING(batch_id) JOIN calc.quote_scheme s USING(scheme_id)
      WHERE ${where} ORDER BY b.created_at DESC,r.delivery_id LIMIT 20 OFFSET ${(page-1)*20})
      SELECT jsonb_build_object('items',COALESCE(jsonb_agg(to_jsonb(entries)-'total_count'),'[]'::jsonb),'total',COALESCE(max(total_count),0),'page',${page})::text FROM entries;`);
  };
  const open=async(p,id,markRead=true)=>{
    p=principal(p);await ready();uuid(id);
    // Receipt access is explicit; global quote authority does not expose inboxes.
    const row=await query(`SELECT COALESCE((SELECT jsonb_build_object('delivery_id',r.delivery_id,'sender_name',b.sender_name,'sent_at',b.created_at,
      'note',b.note,'document',b.document_payload,'document_sha256',b.document_sha256,'read_at',r.read_at)
      FROM calc.quote_delivery_recipient r JOIN calc.quote_delivery_batch b USING(batch_id)
      WHERE r.delivery_id=${q(id)}::uuid AND r.recipient_user_id=${q(p.userId)}),'null'::jsonb)::text;`);
    if(!row)throw error('未找到发给当前登录人的报价。',404);
    if(markRead)row.read_at=await query(`UPDATE calc.quote_delivery_recipient SET read_at=COALESCE(read_at,now()) WHERE delivery_id=${q(id)}::uuid AND recipient_user_id=${q(p.userId)} RETURNING to_jsonb(read_at)::text;`);
    return row;
  };
  const workbook=async(p,id)=>{const row=await open(p,id,false);const bytes=await deliveryWorkbook(row.document);return {bytes,sha256:createHash('sha256').update(bytes).digest('hex'),filename:`${row.document.scheme_no}-V${row.document.quote_version}.xlsx`,document_sha256:row.document_sha256};};
  const output=async(p,id,input)=>{
    p=principal(p);await ready();uuid(id);const outputId=uuid(input.output_id);
    if(!['PRINT','XLSX'].includes(input.kind)||!/^[a-f0-9]{64}$/.test(input.document_sha256||''))throw error('输出记录无效。');
    const value=await query(`WITH logged AS(INSERT INTO calc.quote_delivery_output(output_id,delivery_id,actor_user_id,output_kind,document_sha256)
      SELECT ${q(outputId)}::uuid,r.delivery_id,${q(p.userId)},${q(input.kind)},b.document_sha256 FROM calc.quote_delivery_recipient r JOIN calc.quote_delivery_batch b USING(batch_id)
      WHERE r.delivery_id=${q(id)}::uuid AND r.recipient_user_id=${q(p.userId)} AND b.document_sha256=${q(input.document_sha256)} ON CONFLICT DO NOTHING RETURNING output_id)
      SELECT EXISTS(SELECT 1 FROM logged)::text;`);
    if(!value){const existing=await query(`SELECT EXISTS(SELECT 1 FROM calc.quote_delivery_output WHERE output_id=${q(outputId)}::uuid AND delivery_id=${q(id)}::uuid AND actor_user_id=${q(p.userId)} AND output_kind=${q(input.kind)} AND document_sha256=${q(input.document_sha256)})::text;`);if(!existing)throw error('该输出记录与收到的版本不一致。',409);}
    return {recorded:true,output_id:outputId};
  };
  return {colleagues,versions,send,list,open,workbook,output};
}
