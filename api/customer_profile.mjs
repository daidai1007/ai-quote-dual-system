import {writePermissionSql} from './quote_scheme_service.mjs';
import {orderNatureSql} from '../quote_order_nature.mjs';

export const CUSTOMER_PROFILE_FIELDS=Object.freeze({buyer_address:'需方地址',buyer_phone:'需方电话',buyer_fax:'需方传真',
 buyer_contact:'客户联系人',buyer_representative:'需方代表',buyer_agent:'需方委托代理人',buyer_bank_name:'需方开户行',buyer_bank_account:'需方账号',buyer_tax_no:'需方税号'});
const limits={buyer_address:1000,buyer_phone:80,buyer_fax:80,buyer_contact:120,buyer_representative:120,buyer_agent:120,buyer_bank_name:300,buyer_bank_account:80,buyer_tax_no:80};
const reject=(message,statusCode=400)=>Object.assign(new Error(message),{statusCode});
export function cleanCustomerProfile(value){
 if(!value||typeof value!=='object'||Array.isArray(value))throw reject('客户资料格式无效');
 if(Object.keys(value).some(key=>!Object.hasOwn(CUSTOMER_PROFILE_FIELDS,key)))throw reject('客户资料包含不支持的字段');
 return Object.fromEntries(Object.entries(CUSTOMER_PROFILE_FIELDS).map(([key,label])=>{
  const input=value[key]??'';
  if(typeof input!=='string'||input.length>limits[key]||/[\x00-\x1f\x7f]/.test(input))throw reject(label+'格式无效，请按文本填写');
  return [key,input.trim()];
 }));
}
export function customerProfileView(customer,record=null,matches=0){
 const extra=record?.contract_profile||{};
 const values={...Object.fromEntries(Object.keys(CUSTOMER_PROFILE_FIELDS).filter(k=>Object.hasOwn(extra,k)).map(k=>[k,extra[k]])),
  buyer_address:record?.company_address??extra.buyer_address??'',buyer_phone:record?.contact_phone??extra.buyer_phone??'',buyer_contact:record?.contact_name??extra.buyer_contact??''};
 return {customer_name:customer.customer_name,customer_code:customer.customer_code,version:Number(record?.contract_profile_version||0),
  can_save:matches<=1,fields:cleanCustomerProfile(values)};
}
export function createCustomerProfileStore({query,q,source}){
 const get=async(p,input)=>(await source(p,input.scheme_no,input.version_no)).customer_profile;
 const save=async(p,input)=>{
  const s=await source(p,input.scheme_no,input.version_no),current=s.customer_profile;
  if(!current.can_save)throw reject('存在多份同名客户资料，请先核对客户归属。',409);
  const version=Number(input.expected_version);
  if(!Number.isSafeInteger(version)||version<0)throw reject('客户资料版本无效');
  cleanCustomerProfile(input.fields);
  const fields=cleanCustomerProfile({...current.fields,...input.fields});
  const ready=await query(`SELECT to_jsonb(count(*)=2)::text FROM information_schema.columns WHERE table_schema='calc' AND table_name='ordering_company' AND column_name IN ('contract_profile','contract_profile_version');`);
  if(!ready)throw reject('客户资料暂时无法保存，请联系维护人员更新资料存储；当前填写内容已保留。',503);
  const profile=JSON.stringify(Object.fromEntries(Object.entries(fields).filter(([key])=>!['buyer_address','buyer_phone','buyer_contact'].includes(key)))),code=q(s.customer_code),name=q(s.customer_name);
  const result=await query(`WITH allowed AS(SELECT s.scheme_id FROM calc.quote_scheme s JOIN calc.quote_scheme_version v USING(scheme_id)
   WHERE s.scheme_no=${q(s.scheme_no)} AND v.version_no=${Number(s.version_no)} AND s.status<>'VOID'
   AND ${orderNatureSql('v.snapshot_payload')}='EXTERNAL' AND ${writePermissionSql({...p,role:'USER',departmentId:null},'s')} FOR SHARE OF s), updated AS (
   UPDATE calc.ordering_company SET contact_name=${q(fields.buyer_contact)},contact_phone=${q(fields.buyer_phone)},company_address=${q(fields.buyer_address)},
    contract_profile=${q(profile)}::jsonb,contract_profile_version=contract_profile_version+1
   WHERE company_code=${code} AND company_name=${name} AND contract_profile_version=${version} AND EXISTS(SELECT 1 FROM allowed) RETURNING *
  ), inserted AS (
   INSERT INTO calc.ordering_company(company_code,company_name,contact_name,contact_phone,company_address,is_active,contract_profile,contract_profile_version)
   SELECT ${code},${name},${q(fields.buyer_contact)},${q(fields.buyer_phone)},${q(fields.buyer_address)},TRUE,${q(profile)}::jsonb,1
   WHERE ${version}=0 AND EXISTS(SELECT 1 FROM allowed) AND NOT EXISTS(SELECT 1 FROM updated) AND NOT EXISTS(SELECT 1 FROM calc.ordering_company WHERE company_name=${name})
   ON CONFLICT(company_code) DO NOTHING RETURNING *
  ), changed AS(SELECT * FROM updated UNION ALL SELECT * FROM inserted), audit AS(
   INSERT INTO calc.contract_audit(resource_kind,resource_id,action,actor_user_id,actor_name,detail)
   SELECT 'CUSTOMER_PROFILE',company_code,'SAVED',${q(p.userId)},${q(p.displayName)},jsonb_build_object('version',contract_profile_version) FROM changed
  ) SELECT COALESCE((SELECT to_jsonb(changed) FROM changed),'null'::jsonb)::text;`);
  if(!result)throw reject('客户资料已被其他人修改，请重新加载核对后再保存。',409);
  return customerProfileView(s,result,1);
 };
 return {get,save};
}
