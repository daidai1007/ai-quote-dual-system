/** Immutable selected ledger rows, separate from formal quotation authority. */
import {createHash} from 'node:crypto';
import {upperRmb} from './contract_quote.mjs';
import {CUSTOMER_PROFILE_FIELDS} from './customer_profile.mjs';

export const LEDGER_CUSTOMERS=Object.freeze({
 NUOYUE:Object.freeze({name:'杭州诺玥科技有限公司',group_by:'contract_no'}),
 FANGYUAN:Object.freeze({name:'杭州方圆塑机股份有限公司',group_by:'record'}),
});
const fail=(message,statusCode=400)=>{throw Object.assign(new Error(message),{statusCode});};
const object=(value,keys,label)=>{
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!keys.includes(k)))fail(label+'格式或字段无效');
 return value;
};
const text=(value,label,max=1000,{empty=false,multiline=false,preserve=false}={})=>{
 if(typeof value!=='string'||value.length>max||(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value))||(!multiline&&/[\r\n\t]/.test(value)))fail(label+'格式无效');
 const result=(preserve?value.replace(/\r\n/g,'\n'):value.trim()).normalize('NFC');if(!empty&&!result)fail(label+'不能为空');return result;
};
export const ledgerRecordKey=(fileHash,sheet,row)=>createHash('sha256').update(fileHash+'|'+sheet+'|'+row).digest('hex');
export const stableLedgerValue=value=>JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
export function ledgerDate(value,label,{empty=true}={}){
 if((value===''||value==null)&&empty)return '';
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||Number.isNaN(Date.parse(value))||new Date(value).toISOString().slice(0,10)!==value)fail(label+'格式无效');
 return value;
}
function decimal(value,label,places,{positive=false}={}){
 if(typeof value!=='string'||value.length>24||!/^\d+(?:\.\d+)?$/.test(value))fail(label+'须为台账中的有效数值');
 const [whole,fraction='']=value.split('.');if(fraction.length>places||whole.length>12)fail(label+'精度或范围无效');
 const scaled=BigInt(whole)*10n**BigInt(places)+BigInt((fraction+'0'.repeat(places)).slice(0,places));
 if(positive&&scaled===0n)fail(label+'必须大于0');
 const normalized=whole.replace(/^0+(?=\d)/,'')+(fraction.replace(/0+$/,'')?'.'+fraction.replace(/0+$/,''):'');
 return {text:normalized,scaled};
}
const scalarFields=['contract_no','seller_name','sign_date','delivery_date','seller_address',...Object.keys(CUSTOMER_PROFILE_FIELDS)];
export function cleanLedgerInput(input){
 object(input,['schema','customer_key','source','records','remarks','fields','document_fields','template_version_id','draft_id','expected_version','request_id'],'台账合同');
 if(input.schema!==1||!Object.hasOwn(LEDGER_CUSTOMERS,input.customer_key))fail('台账合同客户或格式不支持');
 const customer=LEDGER_CUSTOMERS[input.customer_key];
 const rawSource=object(input.source,['filename','sha256','size_bytes'],'台账来源');
 const filename=text(rawSource.filename,'台账文件名',200);
 if(!/\.(xls|xlsx)$/i.test(filename)||/[\\/]/.test(filename)||filename.startsWith('~$'))fail('台账文件名无效');
 if(!/^[a-f0-9]{64}$/.test(rawSource.sha256)||!Number.isSafeInteger(rawSource.size_bytes)||rawSource.size_bytes<1||rawSource.size_bytes>64*1024*1024)fail('台账来源校验信息无效');
 if(!Number.isSafeInteger(Number(input.template_version_id))||Number(input.template_version_id)<1)fail('请选择客户合同模板');
 if(!Array.isArray(input.records)||!input.records.length||input.records.length>2000)fail('请选择1至2000条台账明细');
 const used=new Set();
 const records=input.records.map((raw,index)=>{
  object(raw,['record_id','sheet','source_row','serial','contract_no','source_date','delivery_date','name','specification','quantity','unit','unit_price','total','remark'],'台账明细');
  const sheet=text(raw.sheet,'工作表',100),row=Number(raw.source_row);
  if(input.customer_key==='NUOYUE'?sheet!=='诺玥科技':!/^方圆接手\d{4}$/.test(sheet))fail('台账工作表与客户不一致');
  if(!Number.isSafeInteger(row)||row<2||row>200000||raw.record_id!==ledgerRecordKey(rawSource.sha256,sheet,row)||used.has(raw.record_id))fail('台账明细定位重复或无效');
  used.add(raw.record_id);
  const quantity=decimal(raw.quantity,'数量',4,{positive:true}),price=decimal(raw.unit_price,'含税单价',6),total=decimal(raw.total,'小计',2);
  const denominator=10000000000n,expected=(quantity.scaled*price.scaled*100n+denominator/2n)/denominator;
  if(total.scaled!==expected)fail(`第${index+1}行数量、单价与台账小计不一致，请核对`);
  if(total.scaled>=100000000000000n)fail('合同金额超出支持范围');
  const contractNo=text(raw.contract_no??'','台账合同号',200,{empty:input.customer_key!=='NUOYUE'});
  return {record_id:raw.record_id,sheet,source_row:row,serial:text(raw.serial,'台账序号',100),contract_no:contractNo,
   source_date:ledgerDate(raw.source_date??'','台账日期'),delivery_date:ledgerDate(raw.delivery_date??'','交期'),
   name:text(raw.name,'名称',1000,{multiline:true}),specification:text(raw.specification??'','规格',1000,{empty:true,multiline:true}),
   quantity:quantity.text,unit:text(raw.unit,'单位',50),unit_price:price.text,total:total.text,
   remark:text(raw.remark??'','台账备注',5000,{empty:true,multiline:true,preserve:true})};
 });
 const remarks={};object(input.remarks??{},[...used],'备注修改');
 for(const [key,value]of Object.entries(input.remarks??{}))remarks[key]=text(value,'合同备注',5000,{empty:true,multiline:true,preserve:true});
 const fields={};
 if(!input.fields||typeof input.fields!=='object'||Array.isArray(input.fields))fail('合同字段格式无效');
 for(const [key,value]of Object.entries(input.fields)){
  if(!scalarFields.includes(key)&&!/^custom:[^\x00-\x1f{}]{1,80}$/.test(key))fail('合同字段不允许更改来源或人员权限');
  fields[key]=text(value,'合同字段',5000,{empty:true,multiline:true});
 }
 for(const key of ['sign_date','delivery_date'])if(Object.hasOwn(fields,key))fields[key]=ledgerDate(fields[key],key==='sign_date'?'签订日期':'交货日期');
 if(Object.hasOwn(fields,'contract_no'))fields.contract_no=text(fields.contract_no,'合同编号',200,{empty:true});
 const document_fields=[];
 if(!Array.isArray(input.document_fields??[])||(input.document_fields??[]).length>20)fail('分份合同字段无效');
 const groupKeys=new Set(records.map(r=>r.contract_no)),seen=new Set();
 for(const value of input.document_fields??[]){
  object(value,['contract_no','sign_date','delivery_date'],'分份合同字段');
  const key=text(value.contract_no,'分份合同号',200);
  if(input.customer_key!=='NUOYUE'||!groupKeys.has(key)||seen.has(key))fail('分份合同号无效或重复');seen.add(key);
  document_fields.push({contract_no:key,sign_date:ledgerDate(value.sign_date??'','签订日期'),delivery_date:ledgerDate(value.delivery_date??'','交货日期')});
 }
 return {schema:1,customer_key:input.customer_key,source:{filename,sha256:rawSource.sha256,size_bytes:rawSource.size_bytes},
  records,remarks,fields,document_fields,template_version_id:Number(input.template_version_id)};
}
export function ledgerDocuments(data,{requireFields=true}={}){
 const groups=new Map();
 for(const row of data.records){const key=data.customer_key==='NUOYUE'?row.contract_no:'MERGED';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 if(groups.size>20)fail('单次最多生成20份合同，请分批选择');
 return Array.from(groups,([key,rows])=>{
  if(rows.length>500)fail('单份合同最多500行，请核对选择范围');
  const override=data.document_fields.find(d=>d.contract_no===key)||{};
  const sourceDates=[...new Set(rows.map(r=>r.source_date).filter(Boolean))];
  const signDate=override.sign_date||data.fields.sign_date||(data.customer_key==='NUOYUE'&&sourceDates.length===1?sourceDates[0]:'');
  const contractNo=data.customer_key==='NUOYUE'?key:(data.fields.contract_no||'');
  if(requireFields&&!contractNo)fail('请填写方圆本次合并合同的编号');
  if(requireFields&&!signDate)fail('请确认本次合同的签订日期；来源日期不一致时需单独核对');
  const items=rows.map((row,index)=>({number:index+1,name:row.name,specification:row.specification,
   quantity:Number(row.quantity),unit:row.unit,unit_price:Number(row.unit_price),total:Number(row.total),
   remark:Object.hasOwn(data.remarks,row.record_id)?data.remarks[row.record_id]:row.remark}));
  const totalCents=rows.reduce((a,r)=>a+decimal(r.total,'小计',2).scaled,0n);
  if(totalCents>=100000000000000n)fail('合同总额超出支持范围');
  const total=Number(totalCents)/100;
  return {key,contract_no:contractNo,sign_date:signDate,delivery_date:override.delivery_date||data.fields.delivery_date||'',
   quote:{items,total,total_upper:upperRmb(total)},source_records:rows.map(r=>({record_id:r.record_id,sheet:r.sheet,source_row:r.source_row,serial:r.serial,contract_no:r.contract_no}))};
 });
}
export function ledgerCustomer(key){if(!Object.hasOwn(LEDGER_CUSTOMERS,key))fail('台账合同客户不支持');return LEDGER_CUSTOMERS[key];}
