/** One content-dependent minimum for every generated product row.
 * Changes layout only: quotation values, template clauses and formulas remain untouched.
 */
import {DOMParser} from '@xmldom/xmldom';
import {strFromU8} from 'fflate';
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',S='http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const kids=(n,name)=>Array.from(n?.childNodes||[]).filter(x=>x.nodeType===1&&x.localName===name);
const child=(n,name)=>kids(n,name)[0];
const all=(n,ns,name)=>Array.from(n?.getElementsByTagNameNS(ns,name)||[]);
const numeric=(n,key='val',fallback=0)=>Number(n?.getAttributeNS(W,key)||n?.getAttribute('w:'+key)||n?.getAttribute(key))||fallback;
const plain=n=>all(n,W,'t').map(t=>t.textContent).join('');
const attr=(node,key,value)=>node.setAttributeNS(W,'w:'+key,String(value));
const ensure=(parent,ns,prefix,name,first=false)=>{let n=child(parent,name);if(!n){n=parent.ownerDocument.createElementNS(ns,(prefix?prefix+':':'')+name);first?parent.insertBefore(n,parent.firstChild):parent.appendChild(n);}return n;};
const xmlFile=(files,name)=>files[name]?new DOMParser().parseFromString(strFromU8(files[name]),'application/xml'):null;

// Conservative advances avoid depending on installed fonts in the API container.
// Hard line breaks and tab stops count even when a neighbouring row is shorter.
export function wrappedProductLines(value,width,fontSize){
 const available=Math.max(fontSize,width*.90),text=String(value??'').replace(/\r\n?/g,'\n');
 let total=0;
 for(const hardLine of text.split('\n')){
  let lines=1,used=0;
  for(const ch of hardLine){
   const factor=ch==='\t'?2:ch===' '?.5:/[ilI.,:;'`!|]/u.test(ch)?.36:/[0-9]/u.test(ch)?.63:/[mwMW@%]/u.test(ch)?1:/[\x20-\x7e]/u.test(ch)?.72:ch.codePointAt(0)>0xffff?1.3:1.05;
   const advance=fontSize*factor;
   if(used>0&&used+advance>available){lines++;used=0;}
   used+=advance;
  }
  total+=lines;
 }
 return Math.max(1,total);
}
export function sharedProductHeight(cells){
 let height=0;
 for(const c of cells){const lines=wrappedProductLines(c.text,c.width,c.fontSize);height=Math.max(height,lines*c.lineHeight+c.padding);}
 return Math.ceil(Math.max(18,height)*2)/2;
}
function wordDefaultFont(files){const doc=xmlFile(files,'word/styles.xml');const node=all(doc,W,'docDefaults')[0];return numeric(all(node,W,'sz')[0],'val',24)/2;}
function wordCellLayout(cell,width,defaultFont){
 const props=child(cell,'tcPr'),margins=child(props,'tcMar');const margin=side=>{const node=child(margins,side);return node?numeric(node,'w',0)/20:(side==='left'||side==='right'?108/20:0);};
 const sizes=all(cell,W,'sz').map(n=>numeric(n)/2).filter(v=>v>0);const fontSize=sizes.length?Math.max(...sizes):defaultFont;
 const paras=all(cell,W,'p');let text=paras.map(plain).join('\n');let lineHeight=fontSize*1.45,padding=margin('top')+margin('bottom')+5;
 for(const p of paras){const pp=child(p,'pPr'),sp=child(pp,'spacing');const line=numeric(sp,'line');const rule=sp?.getAttributeNS(W,'lineRule');
  if(line)lineHeight=Math.max(lineHeight,rule==='exact'||rule==='atLeast'?line/20:fontSize*line/240*1.45);
  padding+=numeric(sp,'before')/20+numeric(sp,'after')/20;
 }
 const indent=paras.reduce((m,p)=>Math.max(m,numeric(child(child(p,'pPr'),'ind'),'left')/20+numeric(child(child(p,'pPr'),'ind'),'right')/20),0);
 return {text,width:Math.max(fontSize,width-margin('left')-margin('right')-indent-3),fontSize,lineHeight,padding};
}
export function uniformWordProductRows(rows,model){
 if(!rows.length)return;
 const table=rows[0].parentNode,grid=kids(child(table,'tblGrid'),'gridCol').map(n=>numeric(n,'w',1440)/20);
 const defaultFont=wordDefaultFont(model.files),layouts=[];
 for(const row of rows){let col=0;for(const cell of kids(row,'tc')){const span=numeric(child(child(cell,'tcPr'),'gridSpan'),'val',1);const explicit=numeric(child(child(cell,'tcPr'),'tcW'),'w')/20;
  const width=grid.slice(col,col+span).reduce((a,b)=>a+b,0)||explicit||72;layouts.push(wordCellLayout(cell,width,defaultFont));col+=span;
 }}
 const height=sharedProductHeight(layouts);
 const section=all(model.parts.get('word/document.xml'),W,'sectPr')[0],page=numeric(child(section,'pgSz'),'h',16838)/20,margin=child(section,'pgMar');
 const available=page-(numeric(margin,'top',1440)+numeric(margin,'bottom',1440))/20-30;
 if(height>available)throw Object.assign(Error('产品备注或规格超过单页可容纳高度，请拆分说明后重新生成；内容未被截断。'),{statusCode:400});
 for(const row of rows){const pr=ensure(row,W,'w','trPr',true);for(const n of kids(pr,'trHeight'))pr.removeChild(n);const h=ensure(pr,W,'w','trHeight');attr(h,'val',Math.ceil(height*20));attr(h,'hRule','atLeast');
  attr(ensure(pr,W,'w','cantSplit'),'val','1');
  // A minimum, recalculated for this document, keeps rows equal without exact-height clipping.
  for(const cell of kids(row,'tc')){const cp=ensure(cell,W,'w','tcPr',true);attr(ensure(cp,W,'w','vAlign'),'val','center');}
 }
}
const colIndex=letters=>[...letters].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0);
function excelStyles(model){return xmlFile(model.files,'xl/styles.xml');}
function excelText(cell,files){const t=cell.getAttribute('t');if(t==='inlineStr')return all(cell,S,'t').map(n=>n.textContent).join('');if(t==='s'){const ss=xmlFile(files,'xl/sharedStrings.xml');return all(ss,S,'si')[Number(child(cell,'v')?.textContent)]?.textContent||'';}return child(cell,'v')?.textContent||'';}
export function uniformExcelProductRows(rows,model,part){
 if(!rows.length)return;
 const sheet=model.parts.get(part),style=excelStyles(model),xfs=kids(child(style?.documentElement,'cellXfs'),'xf'),fonts=kids(child(style?.documentElement,'fonts'),'font');const layouts=[];
 const columns=all(sheet,S,'col'),merges=all(sheet,S,'mergeCell').map(n=>n.getAttribute('ref').split(':'));
 const widthOf=index=>{let width=8.43;for(const n of columns)if(Number(n.getAttribute('min'))<=index&&index<=Number(n.getAttribute('max')))width=Number(n.getAttribute('width'))||width;return (Math.floor(width*7+5))*.75;};
 for(const row of rows)for(const cell of kids(row,'c')){
  const addr=cell.getAttribute('r'),letters=addr.match(/^[A-Z]+/)[0],index=colIndex(letters),merged=merges.find(([a,b])=>a===addr&&b?.match(/\d+$/)[0]===a.match(/\d+$/)[0]);
  const last=merged?colIndex(merged[1].match(/^[A-Z]+/)[0]):index;let width=0;for(let col=index;col<=last;col++)width+=widthOf(col);
  const xf=xfs[Number(cell.getAttribute('s')||0)],font=fonts[Number(xf?.getAttribute('fontId')||0)],fontSize=Number(child(font,'sz')?.getAttribute('val'))||11;
  layouts.push({text:excelText(cell,model.files),width:Math.max(fontSize,width-10),fontSize,lineHeight:fontSize*1.45,padding:7});
 }
 const height=sharedProductHeight(layouts);
 if(height>409.5)throw Object.assign(Error('产品备注或规格超过 Excel 单行高度上限，请拆分说明后重新生成；内容未被截断。'),{statusCode:400});
 const cache=new Map();let changed=false;
 for(const row of rows){row.setAttribute('ht',String(height));row.setAttribute('customHeight','1');
  for(const cell of kids(row,'c')){
   if(!style||!xfs.length)continue;const id=Number(cell.getAttribute('s')||0);let next=cache.get(id);
   if(next===undefined){const current=child(xfs[id],'alignment');
    if(current?.getAttribute('wrapText')==='1'&&current?.getAttribute('vertical')==='center'&&!current?.hasAttribute('shrinkToFit'))next=id;
    else{const xf=xfs[id].cloneNode(true),a=ensure(xf,S,'','alignment');a.setAttribute('wrapText','1');a.setAttribute('vertical','center');a.removeAttribute('shrinkToFit');xf.setAttribute('applyAlignment','1');const parent=child(style.documentElement,'cellXfs');next=kids(parent,'xf').length;parent.appendChild(xf);parent.setAttribute('count',String(next+1));changed=true;}
    cache.set(id,next);
   }
   cell.setAttribute('s',String(next));
  }
 }
 const ends=keepExcelProductRowsOnPages(rows,model,sheet,widthOf,height);
 if(style&&ends.length){
  // Templates often draw only the top edge of a row. Close the last whole row
  // before a page break so its visible height is as clear as every other row.
  const borders=child(style.documentElement,'borders'),cellXfs=child(style.documentElement,'cellXfs'),styles=new Map();
  for(const row of ends)for(const cell of kids(row,'c')){
   const id=Number(cell.getAttribute('s')||0);let next=styles.get(id);
   if(next===undefined){
    const source=kids(cellXfs,'xf')[id];if(!source||!borders)continue;
    const xf=source.cloneNode(true),original=kids(borders,'border')[Number(xf.getAttribute('borderId')||0)];if(!original)continue;
    if(child(original,'bottom')?.hasAttribute('style')){styles.set(id,id);continue;}
    const border=original.cloneNode(true),oldBottom=child(border,'bottom'),top=child(border,'top');
    const bottom=sheet.createElementNS(S,'bottom');bottom.setAttribute('style',top?.getAttribute('style')||'thin');
    for(const n of Array.from(top?.childNodes||[]))bottom.appendChild(n.cloneNode(true));
    oldBottom?border.replaceChild(bottom,oldBottom):border.insertBefore(bottom,child(border,'diagonal')||null);
    xf.setAttribute('borderId',String(kids(borders,'border').length));xf.setAttribute('applyBorder','1');borders.appendChild(border);borders.setAttribute('count',String(kids(borders,'border').length));
    next=kids(cellXfs,'xf').length;cellXfs.appendChild(xf);cellXfs.setAttribute('count',String(next+1));styles.set(id,next);changed=true;
   }
   cell.setAttribute('s',String(next));
  }
 }
 if(changed)model.parts.set('xl/styles.xml',style);
}
function keepExcelProductRowsOnPages(rows,model,sheet,widthOf,height){
 const setup=child(sheet.documentElement,'pageSetup'),margins=child(sheet.documentElement,'pageMargins');
 const paper={1:[612,792],5:[612,1008],8:[841.9,1190.6],9:[595.3,841.9],11:[419.5,595.3]}[Number(setup?.getAttribute('paperSize'))]||[595.3,841.9];
 const [paperWidth,paperHeight]=setup?.getAttribute('orientation')==='landscape'?[paper[1],paper[0]]:paper;
 const margin=(side,fallback)=>{const value=margins?.getAttribute(side);return value!=null&&value!==''?Number(value)*72:fallback;};
 const sheetIndex=model.sheets.findIndex(s=>s.doc===sheet),names=all(model.parts.get('xl/workbook.xml'),S,'definedName');
 const area=names.find(n=>n.getAttribute('name')==='_xlnm.Print_Area'&&Number(n.getAttribute('localSheetId')||0)===sheetIndex)?.textContent||'';
 const range=area.match(/\$?([A-Z]+)\$?\d+:\$?([A-Z]+)\$?\d+/),first=range?colIndex(range[1]):1,last=range?colIndex(range[2]):Math.max(...rows.flatMap(r=>kids(r,'c').map(c=>colIndex(c.getAttribute('r').match(/^[A-Z]+/)[0]))));
 let width=0;for(let col=first;col<=last;col++)width+=widthOf(col);
 const fitted=Number(setup?.getAttribute('fitToWidth')||0)>0;const scale=fitted?Math.min(1,(paperWidth-margin('left',28.8)-margin('right',28.8))/width):(Number(setup?.getAttribute('scale'))||100)/100;
 const available=(paperHeight-margin('top',36)-margin('bottom',36))/Math.max(.1,scale)-18;
 const defaultHeight=Number(child(sheet.documentElement,'sheetFormatPr')?.getAttribute('defaultRowHeight'))||15;
 const rowHeight=r=>r?.getAttribute('hidden')==='1'?0:Number(r?.getAttribute('ht'))||defaultHeight;
 const start=Number(rows[0].getAttribute('r')),data=child(sheet.documentElement,'sheetData');let used=0;
 for(let n=1;n<start;n++)used+=rowHeight(kids(data,'row').find(r=>Number(r.getAttribute('r'))===n));
 const titles=names.find(n=>n.getAttribute('name')==='_xlnm.Print_Titles'&&Number(n.getAttribute('localSheetId')||0)===sheetIndex)?.textContent||'';
 const repeat=titles.match(/\$?(\d+):\$?(\d+)/);let repeated=0;if(repeat)for(let n=Number(repeat[1]);n<=Number(repeat[2]);n++)repeated+=rowHeight(kids(data,'row').find(r=>Number(r.getAttribute('r'))===n));
 if(height+repeated>available)throw Object.assign(Error('产品备注超过当前打印页可容纳的统一行高，请拆分说明后重新生成。'),{statusCode:400});
 let breaks=child(sheet.documentElement,'rowBreaks');const ends=[];
 for(const [position,row] of rows.entries()){const index=Number(row.getAttribute('r'));
  if(used+height>available){
   if(!breaks){breaks=sheet.createElementNS(S,'rowBreaks');const after=child(sheet.documentElement,'pageSetup')||child(sheet.documentElement,'pageMargins');sheet.documentElement.insertBefore(breaks,after?after.nextSibling:null);}
   if(!kids(breaks,'brk').some(n=>Number(n.getAttribute('id'))===index-1)){const b=sheet.createElementNS(S,'brk');b.setAttribute('id',String(index-1));b.setAttribute('min','0');b.setAttribute('max','16383');b.setAttribute('man','1');breaks.appendChild(b);}
   if(position>0)ends.push(rows[position-1]);used=repeated;
  }
  used+=height;
 }
 if(breaks){breaks.setAttribute('count',String(kids(breaks,'brk').length));breaks.setAttribute('manualBreakCount',String(kids(breaks,'brk').filter(n=>n.getAttribute('man')==='1').length));}
 return ends;
}
