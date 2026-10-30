// Display-only aggregation of frozen line totals. No pricing or state writes.
const cents=value=>value===null||value===undefined||String(value).trim()===''||!Number.isSafeInteger(Math.round(Number(value)*100))?null:Math.round(Number(value)*100);
const quantity=value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))||Number(value)<0?null:Number(value);
const money=value=>(value/100).toFixed(2);
const sum=(values,format)=>{const known=values.filter(v=>v!==null);return known.length?format(known.reduce((a,b)=>a+b,0)):null;};
const quantities=values=>sum(values,v=>Number(v.toFixed(6)));

export function productBreakdown(schemes,{productType,types,product}) {
  const groups=new Map();
  for(const scheme of schemes){
    const lines=new Map();
    for(const item of scheme.products||[]){
      const type=productType(item.product_code);
      if(product&&type!==product)continue;
      const code=types.includes(type)?type:'__unclassified__';
      if(!lines.has(code))lines.set(code,[]);
      lines.get(code).push(item);
    }
    for(const [code,items] of lines){
      const amounts=items.map(p=>cents(p.amount)),counts=items.map(p=>quantity(Object.hasOwn(p,'chart_quantity')?p.chart_quantity:p.quantity));
      const group=groups.get(code)||{product_code:code,product_name:code==='__unclassified__'?'产品待分类':code,items:[],amounts:[],counts:[]};
      group.amounts.push(...amounts);group.counts.push(...counts);
      group.items.push({...scheme,products:items,amount:sum(amounts,money),analysis_amount:sum(amounts,money),quantity:quantities(counts),
        amount_coverage:amounts.filter(v=>v!==null).length,quantity_coverage:counts.filter(v=>v!==null).length,line_count:items.length});
      groups.set(code,group);
    }
  }
  const amountTotal=[...groups.values()].reduce((n,g)=>n+g.amounts.reduce((a,b)=>a+(b??0),0),0);
  const quantityTotal=[...groups.values()].reduce((n,g)=>n+g.counts.reduce((a,b)=>a+(b??0),0),0);
  return [...groups.values()].map(g=>({product_code:g.product_code,product_name:g.product_name,
    amount:sum(g.amounts,money),quantity:quantities(g.counts),scheme_count:g.items.length,line_count:g.amounts.length,
    amount_coverage:g.amounts.filter(v=>v!==null).length,quantity_coverage:g.counts.filter(v=>v!==null).length,
    amount_share:amountTotal>0&&g.amounts.some(v=>v!==null)?g.amounts.reduce((a,b)=>a+(b??0),0)/amountTotal:null,
    quantity_share:quantityTotal>0&&g.counts.some(v=>v!==null)?g.counts.reduce((a,b)=>a+(b??0),0)/quantityTotal:null,items:g.items}));
}

export function contractQuotedTrend(quotes,contracts){
  const days=new Map();
  const details=[];
  for(const [rows,kind,key,dateKey] of [[quotes,'QUOTED','quoted_count','formal_date'],[contracts,'CONTRACT','contract_count','contract_date']]){
    for(const row of rows){
      const date=String(row[dateKey]||'').slice(0,10);if(!date)continue;
      const day=days.get(date)||{date,quoted_count:0,contract_count:0};day[key]++;days.set(date,day);
      details.push({...row,event_kind:kind,event_date:date});
    }
  }
  return {rows:[...days.values()].sort((a,b)=>a.date.localeCompare(b.date)),details};
}
