import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

export function installLocalNameScope(query) {
  // Legacy attachment fixtures predate name-based ownership. Current API
  // guards also query this base-result identity table before calculation.
  query('CREATE TABLE IF NOT EXISTS calc.dual_quote_result(quote_id text PRIMARY KEY);');
  for(const file of ['quote_scheme_center_v1.sql','quote_name_scope_v1.sql']) {
    query(readFileSync(new URL('../../database/migrations/'+file,import.meta.url),'utf8'));
  }
}

// Only own loopback API fixtures. Never use service settings or shared keys.
export async function localApiSession(base,key='local-regression-only') {
  const parsed=new URL(base);
  assert.equal(parsed.protocol,'http:');
  assert.ok(['127.0.0.1','localhost','[::1]'].includes(parsed.hostname));
  const response=await fetch(base+'/api/name-login',{method:'POST',
    headers:{'Content-Type':'application/json','X-AI-Quote-Key':key},
    body:JSON.stringify({name:'本机回归合成人员'})});
  const session=await response.json();
  assert.equal(response.status,200,JSON.stringify(session));
  assert.ok(session.token);
  const headers={'X-AI-Quote-Key':key,Authorization:'Bearer '+session.token};
  return {headers,fetch:(path,options={})=>{
    assert.ok(path.startsWith('/')&&!path.startsWith('//'));
    return fetch(base+path,{...options,headers:{...headers,...options.headers}});
  }};
}
