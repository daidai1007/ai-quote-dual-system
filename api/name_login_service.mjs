import {createHash, randomBytes} from 'node:crypto';

export const ALL_QUOTE_NAMES=Object.freeze(['姜艳娟','翟晓峰','戴晨丽']);
export const authError=(message='姓名会话已失效，请重新输入姓名。',statusCode=401)=>Object.assign(new Error(message),{statusCode,code:'name_session_required'});
export function normalizeName(value){
  if(typeof value!=='string'||/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value)) throw authError('请输入有效姓名，不支持控制字符。',400);
  const name=value.trim().normalize('NFC');
  if(!name||[...name].length>100) throw authError('姓名不能为空，且不能超过100个字符。',400);
  return name;
}
export const nameUserId=name=>'name-user:'+createHash('sha256').update(normalizeName(name),'utf8').digest('hex');
const digest=token=>createHash('sha256').update(String(token)).digest('hex');
export function createNameLoginService({now=Date.now,ttlMs=12*60*60*1000,maxSessions=10000,rateLimit=30}={}){
  const sessions=new Map(),rates=new Map();
  const clean=()=>{const time=now();for(const [key,s]of sessions)if(s.expires<=time)sessions.delete(key);for(const [key,r]of rates)if(r.until<=time)rates.delete(key);};
  const principal=name=>Object.freeze({userId:nameUserId(name),displayName:name,role:'USER',departmentId:null,
    identityMode:'NAME_ONLY',can_view_all_quotes:ALL_QUOTE_NAMES.includes(name),scope:ALL_QUOTE_NAMES.includes(name)?'ALL':'OWN'});
  const publicIdentity=p=>({user_id:p.userId,display_name:p.displayName,identity_mode:'NAME_ONLY',scope:p.scope,can_view_all_quotes:p.can_view_all_quotes});
  const login=(input,address='local')=>{
    clean();const name=normalizeName(input?.name);
    if(Object.keys(input).some(k=>k!=='name'))throw authError('登录仅接受姓名。',400);
    const rate=rates.get(address)||{count:0,until:now()+60000};
    if(!rates.has(address)&&rates.size>=maxSessions)throw authError('登录过于频繁，请稍后重试。',429);
    if(++rate.count>rateLimit)throw authError('登录过于频繁，请稍后重试。',429);
    rates.set(address,rate);
    if(sessions.size>=maxSessions)throw authError('会话数量已达上限，请稍后重试。',503);
    const token=randomBytes(32).toString('base64url'),expires=now()+ttlMs,p=principal(name);
    sessions.set(digest(token),{p,expires});return {token,expires_at:new Date(expires).toISOString(),person:publicIdentity(p)};
  };
  const tokenOf=req=>String(req?.headers?.authorization||'').match(/^Bearer ([A-Za-z0-9_-]{43})$/)?.[1];
  const requireSession=req=>{clean();const token=tokenOf(req),session=token&&sessions.get(digest(token));if(!session)throw authError();return session.p;};
  const describe=req=>{const p=requireSession(req),s=sessions.get(digest(tokenOf(req)));return {person:publicIdentity(p),expires_at:new Date(s.expires).toISOString()};};
  const logout=req=>{requireSession(req);sessions.delete(digest(tokenOf(req)));return {logged_out:true};};
  return {login,requireSession,describe,logout};
}
