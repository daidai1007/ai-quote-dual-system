/** Restricted, deterministic spreadsheet formula evaluation. Never executes JS,
 * macros, links or unsupported formulas and never trusts cached formula values. */
export function evaluateCells(sheets) {
  const cache=new Map(), active=new Set();
  const flat=v=>Array.isArray(v)?v.flat(Infinity):[v];
  const numeric=v=>{if(v===''||v==null)return 0;const n=Number(v);if(!Number.isFinite(n))throw Error('公式引用不是有效数值');return n;};
  const ref=(name,address)=>{
    const key=name+'!'+address.replaceAll('$','').toUpperCase();
    if(cache.has(key))return cache.get(key);
    if(active.has(key))throw Error('模板存在循环公式');
    const cell=sheets.get(name)?.get(address.replaceAll('$','').toUpperCase());
    if(!cell)return 0;
    active.add(key);
    const value=cell.formula?parse(cell.formula,name):cell.value;
    if(typeof value==='number'&&!Number.isFinite(value))throw Error('模板公式结果无效');
    active.delete(key);cache.set(key,value);return value;
  };
  function parse(formula,sheet){
    const src=formula.replace(/^=/,'');let pos=0;
    const ws=()=>{while(/\s/.test(src[pos]||'')&&pos<src.length)pos++;};
    const take=pattern=>{ws();const match=pattern.exec(src.slice(pos));if(match){pos+=match[0].length;return match[0];}return null;};
    function primary(){
      ws();if(take(/^\(/)){const node=expr(0);if(!take(/^\)/))throw Error('公式括号不匹配');return node;}
      const str=take(/^"(?:[^"]|"")*"/);if(str!==null)return {v:str.slice(1,-1).replaceAll('""','"')};
      const num=take(/^(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?/);if(num!==null)return {v:Number(num)};
      const token=take(/^(?:(?:'(?:[^']|'')+'|[\p{L}_][\p{L}\p{N}_.]*)!)?\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?(?![\p{L}\p{N}_])/u);
      if(token){const mark=token.lastIndexOf('!');return {ref:mark<0?token:token.slice(mark+1),sheet:mark<0?sheet:token.slice(0,mark).replace(/^'|'$/g,'').replaceAll("''", "'")};}
      const name=take(/^[A-Za-z_][A-Za-z0-9_.]*/);if(name){
        if(['TRUE','FALSE'].includes(name.toUpperCase()))return {v:name.toUpperCase()==='TRUE'};
        if(!take(/^\(/))throw Error('暂不支持模板中的命名引用：'+name);
        const args=[];if(!take(/^\)/)){do{args.push(expr(0));}while(take(/^[,;]/));if(!take(/^\)/))throw Error('公式参数不完整');}
        return {fn:name.toUpperCase(),args};
      }
      throw Error('暂不支持模板公式：'+formula.slice(0,80));
    }
    const precedence={'=':1,'<>':1,'>':1,'<':1,'>=':1,'<=':1,'&':2,'+':3,'-':3,'*':4,'/':4,'^':5};
    function unary(){const op=take(/^[+-]/);let node=op?{op:op==='-'?'NEG':'POS',a:unary()}:primary();if(take(/^%/))node={op:'/',a:node,b:{v:100}};return node;}
    function expr(min){let a=unary();while(true){ws();const m=/^(<>|>=|<=|[=><&+*/^\-])/.exec(src.slice(pos));if(!m||precedence[m[0]]<min)break;pos+=m[0].length;const op=m[0];a={op,a,b:expr(precedence[op]+(op==='^'?0:1))};}return a;}
    const tree=expr(0);ws();if(pos!==src.length)throw Error('暂不支持模板公式：'+formula.slice(0,80));
    const evaluate=node=>{
      if(Object.hasOwn(node,'v'))return node.v;
      if(node.ref){if(!sheets.has(node.sheet))throw Error('公式引用的工作表不存在');const [a,b]=node.ref.split(':');if(!b)return ref(node.sheet,a);
        const split=x=>{const [,c,r]=/^\$?([A-Za-z]+)\$?(\d+)$/.exec(x);return [c.toUpperCase().split('').reduce((s,v)=>s*26+v.charCodeAt(0)-64,0),Number(r)];};
        const col=n=>{let s='';for(;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
        const [c1,r1]=split(a),[c2,r2]=split(b);if((c2-c1+1)*(r2-r1+1)>20000||c2<c1||r2<r1)throw Error('模板公式范围过大或无效');
        const values=[];for(let r=r1;r<=r2;r++)for(let c=c1;c<=c2;c++)values.push(ref(node.sheet,col(c)+r));return values;
      }
      if(node.fn){if(node.fn==='IF'){if(node.args.length!==3)throw Error('IF 需要三个参数');return evaluate(node.args[evaluate(node.args[0])?1:2]);}
        const args=node.args.map(evaluate),nums=()=>flat(args).filter(v=>v!==''&&v!==null).map(numeric);
        if(node.fn==='SUM')return nums().reduce((a,b)=>a+b,0);
        if(node.fn==='MIN')return Math.min(...nums());if(node.fn==='MAX')return Math.max(...nums());
        if(node.fn==='ABS'&&args.length===1)return Math.abs(numeric(args[0]));
        if(node.fn==='ROUND'&&args.length===2){const n=numeric(args[0]),p=numeric(args[1]);if(!Number.isInteger(p)||Math.abs(p)>10)throw Error('ROUND 位数无效');return Math.sign(n)*Math.round((Math.abs(n)+Number.EPSILON)*10**p)/10**p;}
        throw Error('暂不支持模板公式函数：'+node.fn+'；请调整模板或配置为已确认数值');
      }
      const a=evaluate(node.a);if(node.op==='NEG')return -numeric(a);if(node.op==='POS')return numeric(a);const b=evaluate(node.b);
      switch(node.op){case '+':return numeric(a)+numeric(b);case '-':return numeric(a)-numeric(b);case '*':return numeric(a)*numeric(b);case '/':if(!numeric(b))throw Error('模板公式除以零');return numeric(a)/numeric(b);case '^':return numeric(a)**numeric(b);case '&':return String(a)+String(b);case '=':return a===b;case '<>':return a!==b;case '>':return a>b;case '<':return a<b;case '>=':return a>=b;case '<=':return a<=b;default:throw Error('未知公式运算');}
    };
    return evaluate(tree);
  }
  for(const [sheet,cells] of sheets)for(const [address,cell] of cells)if(cell.formula)cell.result=ref(sheet,address);
}
