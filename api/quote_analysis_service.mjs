/** Read-only analysis of permission-scoped frozen quotations. Outcome recording
 * writes only the separate, audited outcome table, never prices or quote state. */
import {permissionSql, writePermissionSql, operatorNameValue} from './quote_scheme_service.mjs';
import {sessionOperator} from './quote_access_scope.mjs';
import {orderNature,orderNatureSql,validateOrderNature,ORDER_NATURES} from '../quote_order_nature.mjs';

const fail=(message,statusCode=400)=>Object.assign(new Error(message),{statusCode});
const text=value=>String(value??'').trim().normalize('NFC');
// Analysis groups immutable internal calculation codes by the same user-facing
// product types as configuration. Never rewrite stored snapshot/outcome keys.
const PRODUCT_TYPE_ORDER=['JA','JC','JE','JK','JM','JP','JP WIDE','JQ','JS','JS WIDE','操作台'];
const productType=value=>{
  const code=text(value).normalize('NFKC').toUpperCase().replace(/\s+/g,'_');
  const wide=code.match(/^(JP|JS)_WIDE(?:_EXP)?$/);
  if(wide)return `${wide[1]} WIDE`;
  const legacyWide=code.match(/^(?:超宽(JP|JS)|(JP|JS)超宽(?:柜)?)$/);
  if(legacyWide)return `${legacyWide[1]||legacyWide[2]} WIDE`;
  if(['OP_TABLE','OP_TABLE_EXP','操作台'].includes(code))return '操作台';
  const family=code.match(/^(JA|JC|JE|JK|JM|JP|JQ|JS)(?:_(?:SINGLE|DOUBLE|EXP))?$/);
  return family?family[1]:text(value);
};
const sameProduct=(left,right)=>productType(left)===productType(right);
const datePattern=/^\d{4}-\d{2}-\d{2}$/;
const validDate=value=>datePattern.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0,10)===value;
const day=value=>value ? String(value).slice(0,10) : '';
const cents=value=>{
  if(value===null||value===undefined||value==='') return null;
  const n=Number(value); return Number.isFinite(n)&&Number.isSafeInteger(Math.round(n*100))?Math.round(n*100):null;
};
const money=value=>value===null?null:(value/100).toFixed(2);
const ratio=(won,lost)=>won+lost?Number((won*100/(won+lost)).toFixed(1)):null;
const normalizeFilters=(input={})=>{
  const result={};
  for(const key of ['from','to']) {
    const value=text(input[key]);
    if(value && !validDate(value)) throw fail('日期必须为有效的 YYYY-MM-DD。');
    result[key]=value;
  }
  if(result.from && result.to && result.from>result.to) throw fail('开始日期不能晚于结束日期。');
  for(const key of ['customer','product','creator','status','method']) result[key]=text(input[key]);
  result.product=productType(result.product);
  result.order_nature=text(input.order_nature);
  if(result.order_nature)validateOrderNature(result.order_nature);
  if(result.status && !['DRAFT','QUOTED','REVISING','ARCHIVED','VOID'].includes(result.status)) throw fail('无效方案状态。');
  if(result.method && !['QUICK','FORMULA'].includes(result.method)) throw fail('无效报价方式。');
  return result;
};
const inRange=(value,f)=>Boolean(value)&&(!f.from||day(value)>=f.from)&&(!f.to||day(value)<=f.to);
const bandsFor=code=>(productType(code)==='JP'||productType(code)==='JP WIDE'||text(code).startsWith('JP_'))
  ? [[.75,.80],[.80,.85],[.85,.90],[.90,1]] : [[.80,.85],[.85,.90],[.90,.95],[.95,1]];
const classify=(discount,ranges)=>ranges.findIndex(([lo,hi],i)=>discount>=lo&&(discount<hi||(i===ranges.length-1&&discount===hi)));
const groupRates=(outcomes,product)=>{
  const ranges=bandsFor(product);
  const bands=[...ranges.map(([lo,hi],i)=>({key:String(i),label:`${lo.toFixed(2)}–${i===ranges.length-1?'':'<'}${hi.toFixed(2)}`,won:0,lost:0})),
    {key:'outside',label:'其他折扣系数',won:0,lost:0}, {key:'unknown',label:'折扣待确认',won:0,lost:0}];
  for(const row of outcomes) {
    const discount=row.discount===null||row.discount===''?null:Number(row.discount);
    const index=discount===null||!Number.isFinite(discount)?bands.length-1:classify(discount,ranges);
    const band=bands[index<0?bands.length-2:index]; band[row.result==='WON'?'won':'lost']++;
  }
  const visible=bands.filter((band,i)=>i<ranges.length||band.won+band.lost);
  for(const band of visible) Object.assign(band,{sample:band.won+band.lost,rate:ratio(band.won,band.lost),eligible:band.won+band.lost>=20 && !['unknown','outside'].includes(band.key)});
  const eligible=visible.filter(band=>band.eligible);
  const highest=eligible.reduce((best,band)=>!best||band.won*best.sample>best.won*band.sample?band:best,null);
  return {bands:visible,best:eligible.filter(band=>band.won*highest.sample===highest.won*band.sample),sample:outcomes.length,minimum_sample:20};
};

export function buildAnalysis(data,input={}) {
  const filters=normalizeFilters(input), schemes=(data.schemes||[]).map(s=>({...s,order_nature:orderNature(s.order_nature)}));
  const schemeNatures=new Map(schemes.map(s=>[s.scheme_no,s.order_nature]));
  const outcomes=(data.outcomes||[]).map(o=>({...o,order_nature:orderNature(o.order_nature??schemeNatures.get(o.scheme_no))}));
  const natureMatches=row=>!filters.order_nature||row.order_nature===filters.order_nature;
  const matches=s=>(!filters.customer||(filters.customer==='__unassigned__'?!s.customer_code:s.customer_code===filters.customer))
    &&(!filters.product||(s.products||[]).some(p=>sameProduct(p.product_code,filters.product)))
    &&(!filters.creator||text(s.creator).includes(filters.creator))&&(!filters.status||s.status===filters.status)&&natureMatches(s);
  const baseSchemes=schemes.filter(s=>(!filters.creator||text(s.creator).includes(filters.creator))&&(!filters.status||s.status===filters.status));
  const allowedSchemes=schemes.filter(matches);
  const rows=allowedSchemes.filter(s=>inRange(s.formal_date||s.created_date,filters));
  const formal=rows.filter(s=>s.formal_date && s.status!=='VOID');
  // Selecting a product counts only that product's frozen face totals. Never
  // add the entire multi-product quote to each product subtotal.
  const amountOf=s=>filters.product ? (()=>{
    const amounts=s.products.filter(p=>sameProduct(p.product_code,filters.product)).map(p=>cents(p.amount));
    return amounts.length&&amounts.every(x=>x!==null)?amounts.reduce((a,b)=>a+b,0):null;
  })() : cents(s.amount);
  const known=formal.map(amountOf).filter(n=>n!==null), total=known.reduce((a,b)=>a+b,0);
  const customers=new Map(), products=new Map(), ranks=new Map(), trend=new Map(), costs={};
  for(const s of schemes) {
    customers.set(s.customer_code||'__unassigned__',s.customer_name&&s.customer_code?s.customer_name:'客户待确认');
    for(const p of s.products||[]) if(p.product_code) products.set(productType(p.product_code),productType(p.product_code));
  }
  const typeOrder=code=>{const index=PRODUCT_TYPE_ORDER.indexOf(code);return index<0?PRODUCT_TYPE_ORDER.length:index;};
  const orderedProducts=[...products].sort(([a],[b])=>typeOrder(a)-typeOrder(b)||a.localeCompare(b));
  let costCoverage=0;
  for(const s of formal) {
    const amount=amountOf(s), key=s.customer_code||'__unassigned__';
    const r=ranks.get(key)||{customer_code:key,name:s.customer_code?s.customer_name:'客户待确认',cents:0,count:0,amount_coverage:0};
    r.count++; if(amount!==null) {r.cents+=amount;r.amount_coverage++;} ranks.set(key,r);
    const t=trend.get(day(s.formal_date))||{date:day(s.formal_date),count:0,cents:0};
    t.count++;if(amount!==null)t.cents+=amount;trend.set(t.date,t);
    for(const p of s.products||[]) if(!filters.product||sameProduct(p.product_code,filters.product)) {
      if(p.costs&&Object.values(p.costs).every(v=>cents(v)!==null)) {
        costCoverage++;
        for(const [key,value] of Object.entries(p.costs)) costs[key]=(costs[key]||0)+Math.round(cents(value)*Number(p.quantity||1));
      }
    }
  }
  for(const s of allowedSchemes.filter(s=>s.status!=='VOID'&&inRange(s.created_date,filters))) {
    const date=day(s.created_date), t=trend.get(date)||{date,count:0,cents:0};
    t.created_count=(t.created_count||0)+1; trend.set(date,t);
  }
  const schemeMap=new Map(baseSchemes.filter(s=>s.status!=='VOID').map(s=>[s.scheme_no,s]));
  // Result time and formal-quote time are deliberately independent filters.
  const decided=outcomes.filter(o=>['WON','LOST'].includes(o.result)&&schemeMap.has(o.scheme_no)&&natureMatches(o)
    &&inRange(o.result_date,filters)&&(!filters.customer||o.customer_code===filters.customer)
    &&(!filters.product||sameProduct(o.product_code,filters.product))&&(!filters.method||o.quote_method===filters.method));
  const product=filters.product||orderedProducts[0]?.[0]||'';
  const selected=decided.filter(o=>sameProduct(o.product_code,product));
  const classifiedRates=(values,code)=>{
    const grouped=ORDER_NATURES.map(order_nature=>({order_nature,...groupRates(values.filter(o=>o.order_nature===order_nature),code)}));
    const mixed=grouped.filter(g=>g.sample).length>1;
    return {...(mixed?{bands:[],best:[],sample:values.length,minimum_sample:20}:groupRates(values,code)),
      requires_order_nature:mixed,by_order_nature:grouped};
  };
  const customerComparison=[...customers].map(([code,name])=>({customer_code:code,name,
    ...classifiedRates(outcomes.filter(o=>schemeMap.has(o.scheme_no)&&natureMatches(o)&&o.customer_code===code&&sameProduct(o.product_code,product)
      &&['WON','LOST'].includes(o.result)&&inRange(o.result_date,filters)&&(!filters.method||o.quote_method===filters.method)),product)}));
  const productComparison=orderedProducts.map(([code,name])=>({product_code:code,name,
    ...classifiedRates(outcomes.filter(o=>schemeMap.has(o.scheme_no)&&natureMatches(o)&&sameProduct(o.product_code,code)
      &&['WON','LOST'].includes(o.result)&&inRange(o.result_date,filters)&&(!filters.customer||o.customer_code===filters.customer)
      &&(!filters.method||o.quote_method===filters.method)),code)}));
  const selectedSchemeNos=new Set(allowedSchemes.map(s=>s.scheme_no));
  const failures=(data.failures||[]).filter(e=>selectedSchemeNos.has(e.scheme_no)&&inRange(e.date,filters));
  const detailRows=rows.map(s=>({...s,analysis_amount:money(amountOf(s))}));
  return {filters,product_filter_mode:'family-v1',customers:[...customers].map(([code,name])=>({code,name})),products:orderedProducts.map(([code,name])=>({code,name})),
    outcomes_available:Boolean(data.outcomes_available),
    order_nature_summary:ORDER_NATURES.map(order_nature=>{
      const quotes=formal.filter(s=>s.order_nature===order_nature),values=quotes.map(amountOf).filter(v=>v!==null);
      return {order_nature,count:rows.filter(s=>s.order_nature===order_nature).length,
        amount:quotes.length&&!values.length?null:money(values.reduce((a,b)=>a+b,0)),amount_coverage:values.length};
    }),
    summary:{schemes:rows.length,quoted:formal.length,drafts:rows.filter(s=>s.status==='DRAFT').length,
      amount:known.length?money(total):null,average:known.length?money(Math.round(total/known.length)):null,
      amount_coverage:known.length,active_customers:new Set(formal.map(s=>s.customer_code).filter(Boolean)).size,failures:failures.length},
    trend:[...trend.values()].sort((a,b)=>a.date.localeCompare(b.date)).map(t=>({...t,created_count:t.created_count||0,amount:money(t.cents)})),
    ranking:[...ranks.values()].sort((a,b)=>b.cents-a.cents||b.amount_coverage-a.amount_coverage).slice(0,5).map(r=>({...r,amount:r.amount_coverage?money(r.cents):null})),
    costs:Object.fromEntries(Object.entries(costs).map(([k,v])=>[k,money(v)])),cost_coverage:costCoverage,
    details:detailRows,trend_details:allowedSchemes.filter(s=>s.status!=='VOID'&&(inRange(s.formal_date,filters)||inRange(s.created_date,filters)))
      .map(s=>({...s,analysis_amount:money(amountOf(s))})),outcome_records:outcomes.filter(o=>schemeMap.has(o.scheme_no)&&natureMatches(o)),
    recent:detailRows.toSorted((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).slice(0,50),
    failures:failures.slice(0,20),discount:{product_code:product,...classifiedRates(selected,product),customer_comparison:customerComparison,product_comparison:productComparison,
      records:selected.map(o=>({...o}))}};
}

const compactItemsSql=payload=>`COALESCE((SELECT jsonb_agg(jsonb_build_object(
  'product_code',COALESCE(item->>'scheme2_selected_product_code',item->>'product_code'),
  'product_name',COALESCE(item->>'scheme2_selected_product_name',item->>'product_code'),
  'amount',item#>>'{quote_display,total}','discount',item#>>'{quote_display,discount}',
  'quantity',COALESCE(item#>>'{quote_display,quantity}',item->>'quantity','1'),
  'quote_method',COALESCE(item->>'quote_method','QUICK'),
  'costs',CASE WHEN item->'formula' ?& ARRAY['material_cost','auxiliary_cost','labor_cost','attachment_fee','spray_cost','management_fee']
    THEN (SELECT jsonb_object_agg(key,value) FROM jsonb_each(item->'formula') WHERE key=ANY(ARRAY['material_cost','auxiliary_cost','labor_cost','attachment_fee','spray_cost','management_fee']))
    ELSE NULL END)) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(${payload}->'draft_items')='array' THEN ${payload}->'draft_items' ELSE '[]'::jsonb END) item),'[]'::jsonb)`;

export function createQuoteAnalysisService({runPsql,sqlUnicodeText:q}) {
  const query=async sql=>JSON.parse(String(await runPsql(sql)).trim().split(/\r?\n/).at(-1)||'null');
  const read=async(principal)=>{
    const readiness=await query(`SELECT jsonb_build_object('ready',to_regclass('calc.quote_analysis_outcome') IS NOT NULL)::text;`);
    const schemes=await query(`WITH permitted AS (
      SELECT s.*,v.snapshot_payload AS formal_payload,v.version_no AS formal_version,v.quoted_at AS formal_at,
        COALESCE(v.snapshot_payload,snap.snapshot_payload,'{}'::jsonb) AS payload
      FROM calc.quote_scheme s LEFT JOIN calc.quote_scheme_snapshot snap USING(scheme_id)
      LEFT JOIN LATERAL (SELECT v.* FROM calc.quote_scheme_version v WHERE v.scheme_id=s.scheme_id
        ORDER BY v.version_no DESC LIMIT 1) v ON TRUE WHERE ${permissionSql(principal,'s')}
    ), compact AS (
      SELECT s.scheme_id,s.scheme_no,s.status,s.version_no,s.lock_version,s.creator_name_entered AS creator,
        s.last_editor_name_snapshot AS last_editor,s.updated_at,
        to_char(s.created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD') AS created_date,
        CASE WHEN formal_version IS NOT NULL THEN COALESCE(NULLIF(payload#>>'{document,quote_date}',''),to_char(formal_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD')) END AS formal_date,
        CASE WHEN formal_version IS NOT NULL THEN payload#>>'{scheme_summary,quoted_amount}' ELSE s.quoted_amount::text END AS amount,
        COALESCE(NULLIF(payload#>>'{analysis_customer,customer_code}',''), CASE WHEN catalog.matches=1 THEN catalog.code END) AS customer_code,
        COALESCE(catalog.current_name,s.company_name) AS customer_name,formal_version,
        ${orderNatureSql('s.payload')} AS order_nature,
        ${compactItemsSql('s.payload')} AS products,${writePermissionSql(principal,'s')} AS can_record
      FROM permitted s LEFT JOIN LATERAL (SELECT count(*) AS matches,min(company_code) AS code,min(company_name) AS current_name
        FROM calc.ordering_company c WHERE CASE WHEN NULLIF(s.payload#>>'{analysis_customer,customer_code}','') IS NOT NULL
          THEN c.company_code=s.payload#>>'{analysis_customer,customer_code}' ELSE c.company_name=s.company_name END) catalog ON TRUE
    ) SELECT COALESCE(jsonb_agg(to_jsonb(compact)),'[]'::jsonb)::text FROM compact;`);
    const outcomes=readiness.ready ? await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object(
      'outcome_id',o.outcome_id,'revision',o.revision,'scheme_no',s.scheme_no,'version_no',o.version_no,
      'customer_code',o.customer_code,'product_code',o.product_code,'opportunity_key',o.opportunity_key,
      'result',o.result,'result_date',to_char(o.result_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD'),
      'discount',o.discount::text,'quote_method',o.quote_method,'order_nature',${orderNatureSql('v.snapshot_payload')})),'[]'::jsonb)::text
      FROM calc.quote_analysis_outcome o JOIN calc.quote_scheme s USING(scheme_id)
      LEFT JOIN calc.quote_scheme_version v ON v.scheme_id=o.scheme_id AND v.version_no=o.version_no
      WHERE ${permissionSql(principal,'s')};`) : [];
    const failures=await query(`SELECT COALESCE(jsonb_agg(jsonb_build_object('scheme_no',s.scheme_no,
      'date',to_char(e.created_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD'),'kind',e.export_kind)),'[]'::jsonb)::text
      FROM calc.quote_scheme_export e JOIN calc.quote_scheme s USING(scheme_id) WHERE NOT e.succeeded AND ${permissionSql(principal,'s')};`);
    return {schemes,outcomes,failures,outcomes_available:readiness.ready};
  };
  const analyze=async(principal,filters)=>{normalizeFilters(filters);return buildAnalysis(await read(principal),filters);};
  const recordOutcome=async(principal,input)=>{
    input=sessionOperator(principal,input);
    const operator=operatorNameValue(input), scheme=text(input.scheme_no), product=text(input.product_code);
    const customer=text(input.customer_code), opportunity=text(input.opportunity_key), result=text(input.result);
    const revision=Number(input.expected_revision??0), version=Number(input.version_no), resultDate=text(input.result_date);
    if(!/^BJ-\d{8}-\d{6}$/.test(scheme)||!product||!customer||!opportunity||opportunity.length>200
      ||![version,revision].every(Number.isSafeInteger)||version<1||revision<0||!['WON','LOST','PENDING'].includes(result)
      ||!validDate(resultDate)) throw fail('请核对方案、正式版本、客户、产品、商机编号及成交结果日期。');
    // The server selects all values from the immutable formal snapshot; never
    // accept client-supplied discount, price, method, or another user's quote.
    const source=await query(`SELECT COALESCE((SELECT jsonb_build_object('scheme_id',s.scheme_id,
      'customer_code',COALESCE(NULLIF(v.snapshot_payload#>>'{analysis_customer,customer_code}',''),
        CASE WHEN (SELECT count(*) FROM calc.ordering_company c WHERE c.company_name=s.company_name)=1
          THEN (SELECT c.company_code FROM calc.ordering_company c WHERE c.company_name=s.company_name) END),
      'formal_date',COALESCE(v.snapshot_payload#>>'{document,quote_date}',to_char(v.quoted_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD')),
      'products',${compactItemsSql('v.snapshot_payload')}) FROM calc.quote_scheme s
      JOIN calc.quote_scheme_version v USING(scheme_id) WHERE s.scheme_no=${q(scheme)} AND v.version_no=${version}
      AND v.version_no=(SELECT max(v2.version_no) FROM calc.quote_scheme_version v2 WHERE v2.scheme_id=s.scheme_id
        AND COALESCE(v2.snapshot_payload#>>'{document,quote_date}',to_char(v2.quoted_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD'))<=${q(resultDate)})
      AND s.status<>'VOID' AND ${writePermissionSql(principal,'s')}), 'null'::jsonb)::text;`);
    if(!source||source.customer_code!==customer) throw fail('无权登记、客户归属待确认或正式版本不存在。',409);
    if(resultDate<source.formal_date) throw fail('成交结果日期不能早于关联正式报价日期。');
    const lines=(source.products||[]).filter(p=>p.product_code===product);
    if(!lines.length) throw fail('正式报价中没有所选产品。');
    const discounts=new Set(lines.map(p=>p.discount)), methods=new Set(lines.map(p=>p.quote_method));
    const discount=discounts.size===1&&lines[0].discount!==null&&Number.isFinite(Number(lines[0].discount))?Number(lines[0].discount):null;
    const method=methods.size===1&&['QUICK','FORMULA'].includes(lines[0].quote_method)?lines[0].quote_method:'UNKNOWN';
    const saved=await query(`WITH written AS (
      INSERT INTO calc.quote_analysis_outcome(customer_code,opportunity_key,product_code,scheme_id,version_no,result,result_at,discount,quote_method,actor_user_id,actor_name)
      SELECT ${q(customer)},${q(opportunity)},${q(product)},${Number(source.scheme_id)},${version},${q(result)},
        ${q(resultDate)}::date AT TIME ZONE 'Asia/Shanghai',${discount===null?'NULL':discount},${q(method)},${q(principal.userId)},${q(operator)} WHERE ${revision}=0
      ON CONFLICT(customer_code,opportunity_key,product_code) DO NOTHING RETURNING *
    ), corrected AS (
      UPDATE calc.quote_analysis_outcome o SET scheme_id=${Number(source.scheme_id)},version_no=${version},result=${q(result)},
        result_at=${q(resultDate)}::date AT TIME ZONE 'Asia/Shanghai',discount=${discount===null?'NULL':discount},quote_method=${q(method)},
        revision=o.revision+1,actor_user_id=${q(principal.userId)},actor_name=${q(operator)},updated_at=now()
      WHERE ${revision}>0 AND o.customer_code=${q(customer)} AND o.opportunity_key=${q(opportunity)} AND o.product_code=${q(product)} AND o.revision=${revision}
        AND EXISTS(SELECT 1 FROM calc.quote_scheme s WHERE s.scheme_id=o.scheme_id AND ${writePermissionSql(principal,'s')}) RETURNING *
    ), changed AS (SELECT * FROM written UNION ALL SELECT * FROM corrected), audited AS (
      INSERT INTO calc.quote_analysis_outcome_audit(outcome_id,revision,actor_user_id,actor_name,recorded_value)
      SELECT outcome_id,revision,actor_user_id,actor_name,to_jsonb(changed) FROM changed)
    SELECT COALESCE((SELECT jsonb_build_object('recorded',TRUE,'revision',revision) FROM changed),'null'::jsonb)::text;`);
    if(!saved) throw fail('结果已存在或已被修改，请刷新分析后核对结果再登记。',409);
    return saved;
  };
  return {analyze,recordOutcome};
}
