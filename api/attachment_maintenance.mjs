import {isNamePrincipal,q} from './quote_access_scope.mjs';
import {PRODUCT_CODES} from './attachment_cost.mjs';

// Separate capability from quote administration; no inheritance of roles.
export const ATTACHMENT_MAINTAINERS=Object.freeze(['戴晨丽','姜艳娟','翟晓峰','吕芝森']);
export const canMaintainAttachments=p=>isNamePrincipal(p)&&ATTACHMENT_MAINTAINERS.includes(p.displayName);
const fail=(message,statusCode=400)=>Object.assign(new Error(message),{statusCode});
export function requireAttachmentMaintainer(p){if(!canMaintainAttachments(p))throw fail('当前姓名没有公共附件库维护权限。',403);}
const record=x=>x&&typeof x==='object'&&!Array.isArray(x);
const text=(v,label,max,required=false)=>{
 if(v==null&&!required)return '';
 if(typeof v!=='string'||/[\p{Cc}\p{Cf}\p{Cs}]/u.test(v.replace(/\r?\n/g,'')))throw fail(`${label}无效`);
 const s=v.trim().normalize('NFC');if(s.length>max||(required&&!s))throw fail(`${label}${required?'不能为空，且':''}不能超过${max}个字符`);return s;
};
export const maintenanceId=v=>{if(!/^[1-9]\d*$/.test(String(v))||!Number.isSafeInteger(Number(v)))throw fail('附件编号无效');return Number(v);};
const decimal=(v,label)=>{
 if(!['number','string'].includes(typeof v)||!/^\d+(?:\.\d{1,12})?$/.test(String(v))||!Number.isFinite(Number(v))||Number(v)>1e8)
  throw fail(`${label}必须为0至100000000的非负数，最多12位小数`);
 return String(v);
};
const dimension=(v,label)=>v==null||v===''?null:(['string','number'].includes(typeof v)&&Number.isInteger(Number(v))&&Number(v)>0&&Number(v)<=100000?Number(v):(()=>{throw fail(`${label}必须为1至100000的整数毫米`);})());
export const MAINTENANCE_PRODUCTS=Object.freeze([...new Set(Object.values(PRODUCT_CODES).flat())]);
export function normalizeMaintenance(input){
 if(!record(input))throw fail('附件维护内容必须为对象');
 if(Object.keys(input).some(k=>!['action','request_id','attachment_price_id','item','cost_rules','products','reason'].includes(k)))throw fail('附件维护请求含不支持的字段');
 const action=input.action;if(!['CREATE','EDIT','ENABLE','DISABLE'].includes(action))throw fail('附件操作无效');
 if(!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(input.request_id||''))throw fail('保存请求编号无效');
 const out={action,request_id:input.request_id,reason:text(input.reason,'修改原因',500,true)};
 if(action!=='CREATE')out.attachment_price_id=maintenanceId(input.attachment_price_id);
 if(['ENABLE','DISABLE'].includes(action))return out;
 const v=input.item;
 if(!record(v)||Object.keys(v).some(k=>!['item_name','model_code','variant','color','unit','notes','category_level1','category_level2','category_level3','width_mm','height_mm','depth_mm','quick_face_price'].includes(k)))throw fail('附件资料含不支持的字段');
 out.item={item_name:text(v.item_name,'附件名称',160,true),model_code:text(v.model_code,'型号',100),variant:text(v.variant,'规格补充',80),color:text(v.color,'颜色',80),
  unit:text(v.unit,'单位',20,true),notes:text(v.notes,'备注',2000),category_level1:text(v.category_level1,'一级分类',40,true),
  category_level2:text(v.category_level2,'二级分类',160),category_level3:text(v.category_level3,'三级分类',200),
  width_mm:dimension(v.width_mm,'宽度'),height_mm:dimension(v.height_mm,'高度'),depth_mm:dimension(v.depth_mm,'深度'),
  quick_face_price:decimal(v.quick_face_price,'快速报价面价')};
 if(!Array.isArray(input.cost_rules)||input.cost_rules.length<1||input.cost_rules.length>50)throw fail('请填写完整固定成本规则');
 out.cost_rules=input.cost_rules.map(r=>{
  if(!record(r)||Object.keys(r).some(k=>!['rule_id','fixed_cost'].includes(k)))throw fail('第一期仅支持固定成本，不能修改公式或适用规则');
  return {...(action==='EDIT'?{rule_id:maintenanceId(r.rule_id)}:{}),fixed_cost:decimal(r.fixed_cost,'固定成本')};
 });
 if(action==='EDIT'&&new Set(out.cost_rules.map(r=>r.rule_id)).size!==out.cost_rules.length)throw fail('固定成本规则重复');
 if(action==='CREATE'){
  if(out.cost_rules.length!==1)throw fail('新增附件只允许一个固定成本');
  if(!Array.isArray(input.products)||input.products.length>MAINTENANCE_PRODUCTS.length||input.products.some(p=>!MAINTENANCE_PRODUCTS.includes(p)))throw fail('适用产品无效');
  out.products=[...new Set(input.products)];
 }else if(input.products!==undefined)throw fail('现有附件适用产品和材质保持原规则，不可通过价格维护修改');
 return out;
}

export function createAttachmentMaintenance({runPsql}){
 const query=async sql=>JSON.parse(String(await runPsql(sql)).trim().split(/\r?\n/).filter(Boolean).at(-1)||'null');
 async function ready(){if(!await query("SELECT to_jsonb(to_regprocedure('calc.maintain_fixed_attachment(jsonb,text,text)') IS NOT NULL AND to_regclass('calc.attachment_maintenance_audit') IS NOT NULL);"))throw fail('附件维护尚未接入，请先完成配套数据库迁移和API更新。',503);}
 async function list(p){
  requireAttachmentMaintainer(p);await ready();
  const versions=await query("SELECT coalesce(jsonb_agg(data_version),'[]') FROM calc.attachment_catalog_version WHERE status='ACTIVE';");
  if(versions.length!==1)throw fail('当前没有唯一的已启用附件目录，暂不能维护。',409);
  const items=await query(`SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.item_name,x.attachment_price_id),'[]') FROM (
   SELECT p.attachment_price_id,p.item_name,p.model_code,p.variant,p.color,p.unit,p.notes,p.width_mm,p.height_mm,p.depth_mm,
    p.quick_face_price::text AS quick_face_price,p.is_active,p.data_version,c.category_level1,c.category_level2,c.category_level3,
    coalesce(m.revision_no,1) AS revision_no,
    (SELECT coalesce(jsonb_agg(to_jsonb(r)||jsonb_build_object('fixed_cost',r.fixed_cost::text,
      'products',(SELECT coalesce(jsonb_agg(product_code ORDER BY product_code),'[]') FROM calc.attachment_cost_rule_product WHERE rule_id=r.rule_id),
      'materials',(SELECT coalesce(jsonb_agg(material_code ORDER BY material_code),'[]') FROM calc.attachment_cost_rule_material WHERE rule_id=r.rule_id)) ORDER BY r.rule_id),'[]')
     FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id) WHERE b.attachment_price_id=p.attachment_price_id) AS rules
   FROM calc.attachment_price p JOIN calc.attachment_classification c USING(attachment_price_id)
   LEFT JOIN calc.attachment_maintenance_revision m USING(attachment_price_id)
   WHERE p.data_version=${q(versions[0])} AND (m.attachment_price_id IS NULL OR m.is_current)) x;`);
  for(const item of items)item.editable=item.rules.length>0&&item.rules.every(r=>r.method==='FIXED'&&!r.issues?.length);
  return {items,data_version:versions[0],can_maintain:true,products:MAINTENANCE_PRODUCTS,history_policy:'IMMUTABLE_QUOTE_SNAPSHOT'};
 }
 async function audit(p){requireAttachmentMaintainer(p);await ready();return {items:await query(`SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY event_id DESC),'[]') FROM (
  SELECT event_id,actor_name,action,logical_id,old_attachment_price_id,new_attachment_price_id,reason,before_state,after_state,created_at
  FROM calc.attachment_maintenance_audit ORDER BY event_id DESC LIMIT 200) x;`),limit:200};}
 async function save(p,input){
  requireAttachmentMaintainer(p);const payload=normalizeMaintenance(input);await ready();
  try{return await query(`BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='20s'; SELECT calc.maintain_fixed_attachment(${q(JSON.stringify(payload))}::jsonb,${q(p.userId)},${q(p.displayName)}); COMMIT;`);}
  catch(e){
   const known=String(e.message).match(/(附件已被他人修改[^\r\n]*|相同分类[^\r\n]*|固定成本规则已变化[^\r\n]*|附件状态已变化[^\r\n]*|第一期仅支持[^\r\n]*|保存请求已存在[^\r\n]*)/);
   if(known)throw fail(known[1],409);
   if(/query returned no rows|no rows|未找到/.test(e.message))throw fail('附件或已启用目录发生变化，请刷新后重试。',409);
   throw fail('附件保存失败，修改未生效；请刷新核对后重试。',500);
  }
 }
 return {list,audit,save,capabilities:p=>({can_maintain:canMaintainAttachments(p)})};
}
