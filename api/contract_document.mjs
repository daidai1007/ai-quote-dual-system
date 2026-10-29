/** Customer Office templates: preserve untouched ZIP parts, edit only configured
 * fields and detail rows, recompute supported formulas, reject ambiguous input. */
import {unzipSync,zipSync,strFromU8,strToU8} from 'fflate';
import {DOMParser,XMLSerializer} from '@xmldom/xmldom';
import path from 'node:path';
import {evaluateCells} from './contract_formula.mjs';
import {CUSTOMER_PROFILE_FIELDS} from './customer_profile.mjs';
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const S='http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const descendants=(node,ns,name)=>Array.from(node.getElementsByTagNameNS(ns,name));
const children=(node,name)=>Array.from(node.childNodes).filter(n=>n.nodeType===1&&n.localName===name);
const child=(node,name)=>children(node,name)[0];
const xml=node=>new XMLSerializer().serializeToString(node);
const parse=text=>{if(/<!DOCTYPE|<!ENTITY/i.test(text))throw Error('模板含不支持的 XML 声明');return new DOMParser({onError:(level,message)=>{if(level!=='warning')throw Error('模板 XML 无效：'+message);}}).parseFromString(text,'application/xml');};
const fail=message=>{throw Object.assign(new Error(message),{statusCode:400});};
const scalarKeys=['buyer_name','seller_name','contract_no','sign_date','delivery_date',...Object.keys(CUSTOMER_PROFILE_FIELDS),'seller_address','total_amount','total_upper','source_scheme_no','source_version','quote_method'];
const aliases={'客户名称':'buyer_name','购方名称':'buyer_name','需方':'buyer_name','需方名称':'buyer_name','供方名称':'seller_name','合同编号':'contract_no','签约日期':'sign_date','交货日期':'delivery_date','客户联系人':'buyer_contact','客户地址':'buyer_address','需方地址':'buyer_address','电话':'buyer_phone','需方电话':'buyer_phone','传真':'buyer_fax','需方传真':'buyer_fax','委托代理人':'buyer_agent','需方委托代理人':'buyer_agent','开户行':'buyer_bank_name','需方开户行':'buyer_bank_name','帐号':'buyer_bank_account','账号':'buyer_bank_account','需方账号':'buyer_bank_account','税号':'buyer_tax_no','需方税号':'buyer_tax_no','供方地址':'seller_address','合同金额':'total_amount','合计金额':'total_amount','金额大写':'total_upper','报价编号':'source_scheme_no','报价版本':'source_version','报价方式':'quote_method'};
const itemKeys=['number','name','specification','quantity','unit','unit_price','total','remark'];
Object.assign(aliases,{'代表':'buyer_representative','需方代表':'buyer_representative'});
export const CONTRACT_FIELDS=Object.freeze({buyer_name:'需方名称',seller_name:'供方名称',contract_no:'客户合同编号',sign_date:'签约日期',delivery_date:'交货日期',...CUSTOMER_PROFILE_FIELDS,seller_address:'供方地址',total_amount:'合计金额',total_upper:'人民币大写',source_scheme_no:'来源报价编号',source_version:'正式报价版本',quote_method:'采用报价'});
const tokens=text=>[...text.matchAll(/\{\{\s*([^{}]{1,100}?)\s*\}\}/gu)].map(m=>({text:m[0],key:m[1]}));
function archive(bytes,format){
  if(!['docx','xlsx'].includes(format)||!bytes?.length||bytes.length>8*1024*1024)fail('请上传不超过8MB的 DOCX / XLSX 模板；旧格式请先转换');
  let total=0,count=0;
  const files=unzipSync(new Uint8Array(bytes),{filter:entry=>{total+=entry.originalSize;count++;if(total>64*1024*1024||count>2500||entry.originalSize>32*1024*1024||entry.name.includes('..')||entry.name.startsWith('/')||/[\\:\x00-\x1f]/.test(entry.name))fail('模板压缩包内容超出限制');return true;}});
  if(!files['[Content_Types].xml']||!files[format==='docx'?'word/document.xml':'xl/workbook.xml'])fail('文件内容与模板格式不匹配');
  for(const [name,data] of Object.entries(files)){
    if(/vbaproject|activeX|embeddings\/|externalLinks\/|macrosheets\/|queryTables\/|xl\/connections\.xml/i.test(name))fail('模板含宏、嵌入对象或外部数据，暂不支持');
    if(name.endsWith('.rels')){
      const rels=parse(strFromU8(data));
      for(const rel of Array.from(rels.documentElement.childNodes).filter(n=>n.nodeType===1)){
        const target=rel.getAttribute('Target')||'',base=name==='_rels/.rels'?'':path.posix.dirname(path.posix.dirname(name));
        if(String(rel.getAttribute('TargetMode')||'').toLowerCase()==='external'||/^[a-z][a-z0-9+.-]*:|[\\\x00-\x1f]/i.test(target)||path.posix.normalize(path.posix.join(base,target)).startsWith('../'))fail('模板含外部链接或越界关系，请先移除再导入');
      }
    }
  }
  return files;
}
function open(bytes,format){
  const files=archive(bytes,format),parts=new Map(),locations=[],rows=[],sheets=[];
  if(format==='docx'){
    for(const name of Object.keys(files).filter(n=>/^word\/(document|header\d*|footer\d*)\.xml$/.test(n))){
      const doc=parse(strFromU8(files[name]));
      const instructions=[...descendants(doc,W,'instrText').map(n=>n.textContent),...descendants(doc,W,'fldSimple').map(n=>n.getAttributeNS(W,'instr')||'')];
      if(instructions.some(s=>/\b(INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|DATABASE|LINK|HYPERLINK)\b/i.test(s))||descendants(doc,W,'altChunk').length)fail('Word 模板含外部动态域或插入对象，请先转换为普通内容');
      parts.set(name,doc);
      descendants(doc,W,'p').forEach((p,i)=>locations.push({id:name+'#p:'+i,label:(name==='word/document.xml'?'正文':name.replace('word/',''))+' 第'+(i+1)+'段',text:descendants(p,W,'t').map(t=>t.textContent).join(''),node:p,part:name}));
      if(name==='word/document.xml')descendants(doc,W,'tbl').forEach((tbl,t)=>children(tbl,'tr').forEach((tr,r)=>rows.push({id:name+'#table:'+t+':row:'+r,label:'正文表格'+(t+1)+' 第'+(r+1)+'行',cells:children(tr,'tc').map(tc=>descendants(tc,W,'t').map(n=>n.textContent).join('')),node:tr,part:name})));
    }
  }else{
    const strings=files['xl/sharedStrings.xml']?descendants(parse(strFromU8(files['xl/sharedStrings.xml'])),S,'si').map(n=>descendants(n,S,'t').map(t=>t.textContent).join('')):[];
    const workbook=parse(strFromU8(files['xl/workbook.xml'])),rels=parse(strFromU8(files['xl/_rels/workbook.xml.rels']));parts.set('xl/workbook.xml',workbook);
    const links=new Map(Array.from(rels.documentElement.childNodes).filter(n=>n.nodeType===1).map(n=>[n.getAttribute('Id'),n.getAttribute('Target')]));
    for(const sheet of descendants(workbook,S,'sheet')){
      const target=links.get(sheet.getAttributeNS(R,'id'));if(!target)fail('工作表关系无效');
      const part=target.startsWith('/')?target.slice(1):'xl/'+target.replace(/^\.\//,'');if(!files[part])fail('工作表内容不存在');
      const doc=parse(strFromU8(files[part])),name=sheet.getAttribute('name');parts.set(part,doc);sheets.push({name,part,doc});
      const value=c=>{const type=c.getAttribute('t');return type==='s'?strings[Number(child(c,'v')?.textContent)]||'':type==='inlineStr'?descendants(c,S,'t').map(t=>t.textContent).join(''):child(c,'v')?.textContent||'';};
      for(const row of descendants(doc,S,'row')){
        const cells=children(row,'c');rows.push({id:part+'#row:'+row.getAttribute('r'),label:name+' 第'+row.getAttribute('r')+'行',cells:cells.map(value),node:row,part,sheet:name,addresses:cells.map(c=>c.getAttribute('r'))});
        for(const cell of cells)locations.push({id:part+'#'+cell.getAttribute('r'),label:name+'!'+cell.getAttribute('r'),text:value(cell),node:cell,part,sheet:name});
      }
    }
  }
  if(locations.length>30000)fail('模板内容过大');
  return {files,parts,locations,rows,sheets};
}
const coordinates=address=>{const m=/^([A-Z]{1,3})([1-9]\d*)$/.exec(address);if(!m)fail('单元格地址无效');const col=[...m[1]].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0),row=Number(m[2]);if(col>16384||row>1048576)fail('单元格地址超出 Excel 范围');return {col,row};};
function ensureCell(doc,address){
 const {row,col}=coordinates(address),data=descendants(doc,S,'sheetData')[0];if(!data)fail('工作表没有数据区');
 let r=children(data,'row').find(n=>Number(n.getAttribute('r'))===row);
 if(!r){r=doc.createElementNS(S,'row');r.setAttribute('r',String(row));data.insertBefore(r,children(data,'row').find(n=>Number(n.getAttribute('r'))>row)||null);}
 let cell=children(r,'c').find(n=>n.getAttribute('r')===address);
 if(!cell){cell=doc.createElementNS(S,'c');cell.setAttribute('r',address);r.insertBefore(cell,children(r,'c').find(n=>coordinates(n.getAttribute('r')).col>col)||null);}
 return cell;
}
function location(model,id,format){
 let loc=model.locations.find(l=>l.id===id);
 if(!loc&&format==='xlsx'){
  const fragments=String(id).split('#');if(fragments.length!==2)fail('单元格位置无效');const [part,address]=fragments,sheet=model.sheets.find(s=>s.part===part);if(!sheet)return null;
  coordinates(address);const node=ensureCell(sheet.doc,address);loc={id,label:sheet.name+'!'+address,text:'',node,part,sheet:sheet.name};model.locations.push(loc);
 }
 if(loc&&format==='xlsx'){
  const address=loc.id.split('#')[1],point=coordinates(address);
  for(const merge of descendants(model.parts.get(loc.part),S,'mergeCell')){
   const [a,b]=merge.getAttribute('ref').split(':');if(!b)continue;const first=coordinates(a),last=coordinates(b);
   if(point.col>=first.col&&point.col<=last.col&&point.row>=first.row&&point.row<=last.row&&address!==a)fail(loc.label+' 位于合并单元格内部，请配置左上角 '+a);
  }
 }
 return loc;
}
export function inspectContractTemplate(bytes,format){
  const model=open(bytes,format),fields=[];let items=null;
  for(const loc of model.locations)for(const token of tokens(loc.text)){
    if(token.key.startsWith('item.'))continue;
    fields.push({source:aliases[token.key]|| (scalarKeys.includes(token.key)?token.key:'custom:'+token.key),target:loc.id,find:token.text});
  }
  for(const row of model.rows){const columns={};row.cells.forEach((text,index)=>tokens(text).forEach(t=>{if(t.key.startsWith('item.')&&itemKeys.includes(t.key.slice(5)))columns[t.key.slice(5)]=format==='xlsx'?row.addresses[index].replace(/\d+/,''):index;}));if(Object.keys(columns).length&&!items)items={target:row.id,columns};}
  return {format,sheets:model.sheets.map(({name,part})=>({name,part})),fields:CONTRACT_FIELDS,locations:model.locations.map(({id,label,text})=>({id,label,text:text.slice(0,350)})),rows:model.rows.map(({id,label,cells,addresses})=>({id,label,cells:cells.map(s=>s.slice(0,100)),addresses})),suggested:{fields,items}};
}
export function validateContractMapping(bytes,format,mapping){
  const model=open(bytes,format);
  if(!mapping||!Array.isArray(mapping.fields)||mapping.fields.length>100||!mapping.items)fail('请配置合同字段及产品明细行');
  const used=new Set();
  if(format==='xlsx'&&model.rows.some(r=>descendants(r.node,S,'f').some(f=>f.hasAttribute('t'))))fail('模板含共享或数组公式，请先转换为普通公式');
  for(const field of mapping.fields){
    if(!(scalarKeys.includes(field.source)||/^custom:[^\x00-\x1f{}]{1,80}$/.test(field.source)))fail('字段来源无效');
    const loc=location(model,field.target,format);if(!loc)fail('字段位置不存在，请重新配置');
    const find=String(field.find||'');if(find&&(loc.text.split(find).length!==2))fail(loc.label+' 的替换文字需要唯一匹配');
    if(!find&&loc.text.trim()&&!child(loc.node,'f'))fail(loc.label+' 有原内容，请指定要替换的文字');
    if(format==='docx'&&(descendants(loc.node,W,'instrText').length||descendants(loc.node,W,'fldSimple').length))fail('填入位置含 Word 动态域，请先转换为普通文字后配置');
    const key=field.target+'|'+find;if(used.has(key))fail('同一位置不能重复配置');used.add(key);
  }
  const row=model.rows.find(r=>r.id===mapping.items.target);if(!row)fail('产品明细行不存在');
  if(format==='docx'&&descendants(row.node,W,'tblHeader').length)fail('请指定产品样板行，不能使用表头行');
  if(format==='xlsx'&&descendants(model.parts.get(row.part),S,'tableParts').length)fail('产品工作表含结构化表格，请先转换为普通区域再配置');
  if(format==='docx'&&(descendants(row.node,W,'tbl').length||descendants(row.node,W,'vMerge').length))fail('明细行包含嵌套表格或纵向合并，请先调整模板');
  for(const field of mapping.fields){const loc=location(model,field.target,format);let node=loc.node;while(node){if(node===row.node)fail('合同字段不能配置在产品样板行内');node=node.parentNode;}}
  const cols=mapping.items.columns||{};
  for(const key of ['name','quantity','unit_price','total'])if(cols[key]===undefined||cols[key]==='')fail('产品明细缺少名称、数量、单价或金额列');
  if(format==='docx'&&['drawing','bookmarkStart','sdt','instrText','fldSimple'].some(tag=>descendants(row.node,W,tag).length))fail('Word 产品样板行含图片、书签或动态域，请先调整为普通文字行');
  const selected=[];
  for(const [key,col] of Object.entries(cols)){
    if(!itemKeys.includes(key))fail('产品列无效');
    if(format==='docx'&&(!Number.isInteger(Number(col))||Number(col)<0||Number(col)>=row.cells.length))fail('Word 明细列号无效');
    if(format==='xlsx'){if(!/^[A-Z]{1,3}$/.test(String(col)))fail('Excel 明细列请填写 A / B 等列字母');location(model,row.part+'#'+col+row.node.getAttribute('r'),'xlsx');}selected.push(String(col));
  }
  if(new Set(selected).size!==selected.length)fail('产品列位置不能重复');
  for(const required of ['buyer_name','total_amount'])if(!mapping.fields.some(f=>f.source===required))fail('请配置购方名称与合计金额位置');
  return structuredClone(mapping);
}
function replaceWord(p,find,value){
  const nodes=descendants(p,W,'t'),text=nodes.map(t=>t.textContent).join('');
  if(!nodes.length){const doc=p.ownerDocument,r=doc.createElementNS(W,'w:r'),t=doc.createElementNS(W,'w:t');t.textContent=value;r.appendChild(t);p.appendChild(r);return;}
  const start=find?text.indexOf(find):0,end=find?start+find.length:text.length;if(start<0)fail('模板字段位置与配置不一致');
  let offset=0,inserted=false;
  for(const node of nodes){const old=node.textContent,left=offset,right=offset+old.length;offset=right;
    if(right<=start||left>=end&&!(start===end&&left===start&&!inserted))continue;
    const before=old.slice(0,Math.max(0,start-left)),after=old.slice(Math.max(0,end-left));
    node.textContent=before+(!inserted?value:'')+after;node.setAttribute('xml:space','preserve');inserted=true;
  }
  if(!inserted){nodes[0].textContent=value;for(const n of nodes.slice(1))n.textContent='';}
}
function setCell(cell,value){
  for(const n of Array.from(cell.childNodes))if(n.nodeType===1&&['v','is','f'].includes(n.localName))cell.removeChild(n);
  const doc=cell.ownerDocument;if(typeof value==='number'){cell.removeAttribute('t');const v=doc.createElementNS(S,'v');v.textContent=String(value);cell.appendChild(v);}else{cell.setAttribute('t','inlineStr');const is=doc.createElementNS(S,'is'),t=doc.createElementNS(S,'t');t.setAttribute('xml:space','preserve');t.textContent=String(value??'');is.appendChild(t);cell.appendChild(is);}
}
const rowOf=address=>Number(address.match(/\d+$/)?.[0]);
const moveAddress=(address,at,delta)=>address.replace(/(\$?)(\d+)/g,(m,d,r)=>d+(Number(r)>=at?Number(r)+delta:r));
function shiftFormula(formula,sheet,changedSheet,at,delta,expandRow){
  return formula.split(/("(?:[^"]|"")*")/g).map((segment,index)=>index%2?segment:segment.replace(/((?:'(?:[^']|'')+'|[\p{L}_][\p{L}\p{N}_.]*)!)?(\$?[A-Z]{1,3}\$?[1-9]\d*)(?::(\$?[A-Z]{1,3}\$?[1-9]\d*))?/gu,(full,prefix,a,b)=>{
    const target=prefix?prefix.slice(0,-1).replace(/^'|'$/g,'').replaceAll("''", "'"):sheet;
    if(target!==changedSheet)return full;
    let end=b?moveAddress(b,at,delta):'';
    if(b&&rowOf(a)<=expandRow&&rowOf(b)===expandRow)end=b.replace(/\d+$/,String(rowOf(b)+delta));
    return (prefix||'')+moveAddress(a,at,delta)+(b?':'+end:'');
  })).join('');
}
export function renderContractTemplate(bytes,format,mapping,values,items){
  validateContractMapping(bytes,format,mapping);
  if(!Array.isArray(items)||!items.length||items.length>500)fail('合同产品数量应为1至500行');
  const model=open(bytes,format),row=model.rows.find(r=>r.id===mapping.items.target),expectations=[];
  for(const field of mapping.fields){
    const loc=location(model,field.target,format),find=String(field.find||'');
    if(field.source==='delivery_date'&&(values.delivery_date==null||String(values.delivery_date).trim()==='')){
      // Delivery terms already belong to the customer's template. A legacy
      // mapping must not clear or replace that original wording.
      if(tokens(loc.text).some(token=>(aliases[token.key]||token.key)==='delivery_date'))
        fail('请在客户合同模板中填写交货日期或交货条款，交货日期不再由合同生成页面填写。');
      continue;
    }
    const optional=field.source==='contract_no'||['buyer_contact','buyer_phone','buyer_fax','buyer_representative','buyer_agent','buyer_bank_name','buyer_bank_account','buyer_tax_no'].includes(field.source);
    const value=values[field.source]??(optional?'':undefined);
    if(!optional&&(value===undefined||value===null||String(value).trim()===''))fail('请补齐合同字段：'+(CONTRACT_FIELDS[field.source]||field.source.replace('custom:','')));
    if(format==='docx')replaceWord(loc.node,find,typeof value==='number'?value.toFixed(2):String(value));
    else if(child(loc.node,'f')){if(field.source!=='total_amount')fail('有公式的字段仅允许用于核对合同总额');expectations.push({part:loc.part,cell:loc.node,value:Number(value)});}
    else{const result=find?loc.text.replace(find,()=>String(value)):value;setCell(loc.node,find&&loc.text!==find?result:(field.source==='total_amount'?Number(value):String(value)));loc.text=String(result);}
  }
  if(format==='docx'){
    for(let i=0;i<items.length;i++){
      const clone=row.node.cloneNode(true),cells=children(clone,'tc');
      for(const [key,index] of Object.entries(mapping.items.columns)){
        const cell=cells[Number(index)],paras=descendants(cell,W,'p');if(!paras.length)fail('产品单元格结构不支持');
        const value=items[i][key]??'',text=typeof value==='number'&&['unit_price','total'].includes(key)?value.toFixed(2):String(value);
        for(const p of paras)for(const t of descendants(p,W,'t'))t.textContent='';replaceWord(paras[0],'',text);
      }
      row.node.parentNode.insertBefore(clone,row.node);
    }
    row.node.parentNode.removeChild(row.node);
    for(const part of model.parts.values())for(const node of [...descendants(part,W,'t')])if(/[\r\n]/.test(node.textContent)){
      const lines=node.textContent.replace(/\r\n?/g,'\n').split('\n');
      lines.forEach((line,index)=>{if(index)node.parentNode.insertBefore(node.ownerDocument.createElementNS(W,'w:br'),node);const t=node.cloneNode(false);t.setAttribute('xml:space','preserve');t.textContent=line;node.parentNode.insertBefore(t,node);});node.parentNode.removeChild(node);
    }
  }else{
    const start=Number(row.node.getAttribute('r')),at=start+1,delta=items.length-1,doc=model.parts.get(row.part),sheetData=row.node.parentNode;
    if(delta){
      // Shift every sheet's formulas that reference this sheet, including totals.
      for(const sheet of model.sheets)for(const f of descendants(sheet.doc,S,'f')){
        if(f.hasAttribute('t'))fail('模板含共享或数组公式，请先转换为普通公式');
        f.textContent=shiftFormula(f.textContent,sheet.name,row.sheet,at,delta,start);
      }
      for(const existing of descendants(doc,S,'row'))if(Number(existing.getAttribute('r'))>=at){existing.setAttribute('r',String(Number(existing.getAttribute('r'))+delta));for(const c of children(existing,'c'))c.setAttribute('r',moveAddress(c.getAttribute('r'),at,delta));}
      for(const tag of ['mergeCell','dimension','autoFilter','conditionalFormatting','dataValidation','hyperlink'])for(const node of descendants(doc,S,tag))for(const attr of ['ref','sqref'])if(node.hasAttribute(attr)){
        const old=node.getAttribute(attr),[a,b]=old.split(':');
        if(tag==='mergeCell'&&b&&rowOf(a)<=start&&rowOf(b)>start)fail('明细行跨越纵向合并单元格，请先调整模板');
        node.setAttribute(attr,old.split(' ').map(ref=>ref.split(':').map(v=>moveAddress(v,at,delta)).join(':')).join(' '));
      }
      for(const merged of [...descendants(doc,S,'mergeCell')]){const range=merged.getAttribute('ref');if(range.split(':').every(a=>rowOf(a)===start))for(let n=1;n<=delta;n++){const clone=merged.cloneNode(true);clone.setAttribute('ref',range.replace(/\d+/g,()=>String(start+n)));merged.parentNode.appendChild(clone);}}
      const merges=descendants(doc,S,'mergeCells')[0];if(merges)merges.setAttribute('count',String(children(merges,'mergeCell').length));
      for(const n of descendants(model.parts.get('xl/workbook.xml'),S,'definedName'))n.textContent=shiftFormula(n.textContent,'',row.sheet,at,delta,start);
      const relPart=path.posix.join(path.posix.dirname(row.part),'_rels',path.posix.basename(row.part)+'.rels');
      const drawingParts=model.files[relPart]?Array.from(parse(strFromU8(model.files[relPart])).documentElement.childNodes).filter(n=>n.nodeType===1&&/\/drawing$/.test(n.getAttribute('Type'))).map(n=>path.posix.normalize(path.posix.join(path.posix.dirname(row.part),n.getAttribute('Target')))):[];
      for(const name of drawingParts){
        if(!model.files[name])fail('工作表图片关系无效');
        const drawing=parse(strFromU8(model.files[name]));for(const node of descendants(drawing,'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing','row'))if(Number(node.textContent)>=at-1)node.textContent=String(Number(node.textContent)+delta);model.parts.set(name,drawing);
      }
    }
    let anchor=row.node.nextSibling;
    for(let i=0;i<items.length;i++){
      const clone=i?row.node.cloneNode(true):row.node;clone.setAttribute('r',String(start+i));
      for(const cell of children(clone,'c')){cell.setAttribute('r',cell.getAttribute('r').replace(/\d+$/,String(start+i)));const f=child(cell,'f');if(f&&i)f.textContent=f.textContent.split(/("(?:[^"]|"")*")/g).map((segment,index)=>index%2?segment:segment.replace(/(\$?)([A-Z]{1,3})(\$?)(\d+)/g,(m,dc,c,dr,r)=>dc+c+dr+(dr?r:Number(r)+i))).join('');}
      for(const [key,col] of Object.entries(mapping.items.columns)){
        let cell=children(clone,'c').find(c=>c.getAttribute('r')===col+(start+i));if(!cell){cell=doc.createElementNS(S,'c');cell.setAttribute('r',col+(start+i));clone.insertBefore(cell,children(clone,'c').find(n=>coordinates(n.getAttribute('r')).col>coordinates(col+'1').col)||null);}setCell(cell,items[i][key]??'');
      }
      if(i)sheetData.insertBefore(clone,anchor);
    }
    const sheetMaps=new Map();
    for(const sheet of model.sheets){const cells=new Map();for(const cell of descendants(sheet.doc,S,'c')){const type=cell.getAttribute('t');const loc=model.locations.find(l=>l.node===cell);let value=type==='inlineStr'?descendants(cell,S,'t').map(t=>t.textContent).join(''):type==='s'?loc?.text||'':child(cell,'v')?.textContent||'';if(!['s','inlineStr','str'].includes(type)&&value!=='')value=Number(value);cells.set(cell.getAttribute('r'),{value,formula:child(cell,'f')?.textContent,node:cell});}sheetMaps.set(sheet.name,cells);}
    for(const cells of sheetMaps.values())for(const cell of cells.values())if(typeof cell.value==='string'&&tokens(cell.value).length)fail('合同仍有未填字段，请完善模板配置');
    evaluateCells(sheetMaps);
    for(const cells of sheetMaps.values())for(const cell of cells.values())if(cell.formula){const result=cell.result;const node=cell.node;node.removeAttribute('t');for(const v of children(node,'v'))node.removeChild(v);const v=node.ownerDocument.createElementNS(S,'v');v.textContent=typeof result==='boolean'?String(Number(result)):String(result);if(typeof result==='string')node.setAttribute('t','str');node.appendChild(v);}
    for(const check of expectations){const sheet=model.sheets.find(s=>s.part===check.part);const result=sheetMaps.get(sheet.name).get(check.cell.getAttribute('r'));if(Math.abs(Number(result.result??result.value)-check.value)>.005)fail('模板合计公式与正式报价总额不一致');}
    for(const sheet of model.sheets){const dim=descendants(sheet.doc,S,'dimension')[0];if(dim&&delta){const last=descendants(sheet.doc,S,'row').at(-1);const range=dim.getAttribute('ref');if(last&&rowOf(range.split(':').at(-1))<Number(last.getAttribute('r')))dim.setAttribute('ref',range.replace(/\d+$/,last.getAttribute('r')));}}
    for(const [name] of Object.entries(model.files))if(/^xl\/calcChain\.xml$/.test(name))delete model.files[name];
    // Remove the calculation-chain relationship; all supported caches were computed above.
    for(const name of ['[Content_Types].xml','xl/_rels/workbook.xml.rels'])if(model.files[name]){const part=parse(strFromU8(model.files[name]));for(const node of Array.from(part.documentElement.childNodes))if(node.nodeType===1&&Array.from(node.attributes).some(a=>/calcChain/.test(a.value)))part.documentElement.removeChild(node);model.parts.set(name,part);}
  }
  for(const [name,doc] of model.parts){const text=xml(doc);if(/\{\{[^{}]+\}\}/u.test(text))fail('合同仍有未填字段，请完善模板配置');model.files[name]=strToU8(text);}
  return Buffer.from(zipSync(model.files,{level:6}));
}
