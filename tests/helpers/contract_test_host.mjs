/** Own test cluster + real api/server; synthetic fixtures only. Stop on stdin. */
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {startLocalPostgres} from './local_postgres.mjs';
import {createQuoteSchemeService} from '../../api/quote_scheme_service.mjs';
import {wordTemplate,excelTemplate,sampleQuote} from './contract_fixtures.mjs';
const root=fileURLToPath(new URL('../../',import.meta.url));
const state=path.resolve(process.argv[2]);
const pg=await startLocalPostgres();let child;
try{
 pg.query("CREATE SCHEMA calc;CREATE TABLE calc.dual_quote_result(quote_id text);CREATE TABLE calc.ordering_company(company_code text,company_name text);INSERT INTO calc.ordering_company VALUES('LOCAL-A','本机测试客户 A'),('LOCAL-CUSTOMER','本机回归客户');");
 for(const migration of ['quote_scheme_center_v1.sql','quote_analysis_v1.sql','quote_name_scope_v1.sql','contract_templates_v1.sql']){
  // Analytics migration name differs between baselines; optional and unused here.
  if(migration==='quote_analysis_v1.sql')continue;
  pg.query(await fs.readFile(path.join(root,'database/migrations',migration),'utf8'));
 }
 const q=v=>v==null?'NULL':`'${String(v).replaceAll("'","''")}'`;
 const quotes=createQuoteSchemeService({runPsql:async s=>pg.query(s),sqlUnicodeText:q,sqlNumber:v=>String(Number(v))});
 const owner={userId:'name-user:'+createHash('sha256').update('本机人员甲').digest('hex'),displayName:'本机人员甲',role:'USER',identityMode:'NAME_ONLY',scope:'OWN',can_view_all_quotes:false};
 const snapshot={company:'本机测试客户 A',analysis_customer:{customer_code:'LOCAL-A'},scheme_summary:{company:'本机测试客户 A',quoted_amount:650.3},draft_items:sampleQuote.items.map(r=>({name:r.name,quantity:r.quantity,attachments:[],formula:{material_cost:r.unit_price,auxiliary_cost:0,labor_cost:0,spray_cost:0,management_fee:0},formula_discount:1,quote_display:{...r}}))};
 const created=await quotes.create(owner,{snapshot,operator_name:owner.displayName});
 await quotes.exportResult(owner,created.scheme_no,{expected_version:1,kind:'XLSX',succeeded:true,snapshot,operator_name:owner.displayName});
 const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
 const environment={...process.env,AI_QUOTE_API_HOST:'127.0.0.1',PORT:String(port),AI_QUOTE_API_KEY:'local-shared-test',PSQL_PATH:process.env.LOCAL_TEST_POSTGRES_BIN?path.join(process.env.LOCAL_TEST_POSTGRES_BIN,'psql.exe'):'G:/PostgreSQL/18/bin/psql.exe',
  AI_QUOTE_DB_HOST:'127.0.0.1',AI_QUOTE_DB_PORT:pg.query('SHOW port;'),AI_QUOTE_DB_USER:pg.query('SELECT current_user;'),AI_QUOTE_DB_NAME:'postgres',PGSSLMODE:'disable',PGCLIENTENCODING:'UTF8',
  AI_QUOTE_PRINCIPALS_JSON:JSON.stringify([{api_key_sha256:createHash('sha256').update('local-contract-owner').digest('hex'),user_id:owner.userId,display_name:owner.displayName,role:'USER'},
   {api_key_sha256:createHash('sha256').update('local-contract-other').digest('hex'),user_id:'local-other',display_name:'其他本机人员',role:'USER'}])};
 for(const key of ['DATABASE_URL','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGPASSFILE','PGSERVICE','PGSERVICEFILE','PGOPTIONS','RENDER'])delete environment[key];
 const log=await fs.open(state+'.api.log','w');
 child=spawn(process.execPath,['api/server.mjs'],{cwd:root,env:environment,windowsHide:true,stdio:['ignore',log.fd,log.fd]});
 const base='http://127.0.0.1:'+port;let ready=false;
 for(let i=0;i<100;i++){
  if(child.exitCode!==null)throw Error('Local API stopped');
  try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 if(!ready)throw Error('Local API did not start');
 await fs.writeFile(path.join(path.dirname(state),'local-template.docx'),wordTemplate());await fs.writeFile(path.join(path.dirname(state),'local-template.xlsx'),excelTemplate());
 await fs.writeFile(state,JSON.stringify({base,scheme_no:created.scheme_no,key:'local-contract-owner',customer_code:'LOCAL-A',name_login:true,connection:pg.connection}));
 await new Promise(resolve=>{process.stdin.once('data',resolve);process.stdin.once('end',resolve);});
}finally{if(child&&child.exitCode===null){child.kill();await new Promise(resolve=>child.once('exit',resolve));}await pg.close();}
