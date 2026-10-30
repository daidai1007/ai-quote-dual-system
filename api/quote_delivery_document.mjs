import ExcelJS from '@excel.js/exceljs';
import {contractQuote} from './contract_quote.mjs';
import {snapshotOrderNature,validateOrderNature} from '../quote_order_nature.mjs';
import {quickFreightFee} from '../quick_discount_rules.mjs';

export const SELLER=Object.freeze({name:'浙江京能电力设备有限公司',address:'杭州临安横畈工业功能区桑园路18号',phone:'0571-88520091',fax:'0571-88520077'});
export const displayVersion=(snapshot,fallback)=>{
  const value=Number(snapshot?.quote_management?.current||fallback);
  if(!Number.isSafeInteger(value)||value<1)throw Object.assign(Error('正式报价版本无效。'),{statusCode:409});
  return value;
};
// Retain the old wire column for older clients; the new cost UI omits it.
export const COST_HEADERS=['序号','名称','产品','尺寸','数量','已选附件','附件面价','面价','材料差价','折扣系数','报价','报价总价','成本单价','材料成本','辅材成本','人工成本','附件成本','喷涂费用','管理费用','运费','成本总价','毛利率','自制件重量','成本明细','固定报价','折扣面价','净利率','制造成本','报价运费','税费'];
const numeric=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))?Number(value):null;
const detailKeys=['type','name','spec','formula','quantity','unit','unit_price','base_amount','factor','amount','note'];
function priceBreakdown(saved,face){
  if(saved?.schema!==1||saved.basis!=='per_unit_set_v1')return null;
  const cents=value=>Math.round(Number(value)*100);
  const result={schema:1,basis:saved.basis};
  for(const key of ['fixed','discounted']){
    const group=saved[key];
    if(!Array.isArray(group?.rows)||group.rows.length>1000||numeric(group.total)===null)return null;
    const rows=[];
    for(const row of group.rows){
      if(!row||typeof row.category!=='string'||!row.category.trim()||
        ['original','discount','amount'].some(k=>numeric(row[k])===null))return null;
      rows.push({category:row.category.slice(0,200),original:numeric(row.original),discount:numeric(row.discount),amount:numeric(row.amount)});
    }
    if(rows.reduce((total,row)=>total+cents(row.amount),0)!==cents(group.total))return null;
    result[key]={rows,total:numeric(group.total)};
  }
  if(cents(result.fixed.total)+cents(result.discounted.total)!==cents(face.unit_price))return null;
  result.total=face.unit_price;
  return result;
}
function costSnapshot(snapshot,quote){
  const source=snapshot.contract_quote_snapshot?.items||snapshot.draft_items;
  return {schema:1,headers:COST_HEADERS,items:quote.items.map((face,index)=>{
    const item=source[index]||{},f=item.formula||{},saved=item.quote_cost_display;
    const values={序号:index+1,名称:face.name,产品:String(item.product_code||item.product_name||''),尺寸:face.specification,数量:face.quantity,
      已选附件:(item.attachments||[]).map(a=>String(a.item_name||a.model_code||'')).filter(Boolean).join('、'),
      附件面价:numeric(item.quote_display?.attachment_face_price),面价:numeric(item.quick?.base_price),固定报价:null,折扣面价:null,材料差价:numeric(item.quote_display?.material_difference),
      折扣系数:numeric(item.quick_discount),报价:face.unit_price,报价总价:face.total,成本单价:numeric(f.total_cost),
      材料成本:numeric(f.material_cost),辅材成本:numeric(f.auxiliary_cost),人工成本:numeric(f.labor_cost),附件成本:numeric(f.attachment_fee),
      喷涂费用:numeric(f.spray_cost),管理费用:numeric(f.management_fee),运费:numeric(item.freight_fee??item.freight),
      成本总价:null,毛利率:null,净利率:null,制造成本:numeric(f.manufacturing_cost),税费:numeric(f.tax_cost),报价运费:quickFreightFee(item),自制件重量:numeric(item.self_made_weight),成本明细:'查看'};
    const columns=COST_HEADERS.map(key=>saved?.schema===1&&Object.hasOwn(saved.values||{},key)?saved.values[key]:values[key]);
    return {columns:columns.map(value=>typeof value==='number'?numeric(value):typeof value==='string'?value.slice(0,5000):null),
      price_breakdown:priceBreakdown(saved?.price_breakdown,face),
      details:Array.isArray(item.cost_detail_rows)?item.cost_detail_rows.filter(r=>r&&typeof r==='object').map(r=>Object.fromEntries(detailKeys.filter(k=>Object.hasOwn(r,k)).map(k=>[k,typeof r[k]==='string'?r[k].slice(0,5000):numeric(r[k])]))):[]};
  })};
}
/** Allowlisted quote and version costs; never expose IDs, paths or other versions. */
export function deliveryDocument(snapshot,schemeNo,sourceVersion,quotedDate=''){
  const nature=validateOrderNature(snapshotOrderNature(snapshot),true);
  const quote=contractQuote(snapshot,'QUICK');
  return {schema:1,scheme_no:schemeNo,source_version_no:sourceVersion,
    quote_version:displayVersion(snapshot,sourceVersion),order_nature:nature,
    quote_date:String(snapshot.document?.quote_date||quotedDate).slice(0,10),
    customer:String(snapshot.company||snapshot.scheme_summary?.company||''),seller:{...SELLER},
    currency:'CNY',cost_snapshot:costSnapshot(snapshot,quote),items:quote.items.map(({number,name,specification,quantity,unit,unit_price,total,remark})=>
      ({number,name,specification,quantity,unit,unit_price,total,remark})),total:quote.total};
}

/** A recipient receives the quoted prices only. No cost sheet or repricing. */
export async function deliveryWorkbook(document){
  const workbook=new ExcelJS.Workbook();
  workbook.creator='AI 双报价系统';
  const sheet=workbook.addWorksheet('报价单');
  sheet.columns=[{width:8},{width:23},{width:26},{width:10},{width:8},{width:17},{width:19},{width:38}];
  sheet.mergeCells('A1:H1');sheet.getCell('A1').value='报价单';
  sheet.getCell('A1').font={name:'微软雅黑',size:20,bold:true};sheet.getCell('A1').alignment={horizontal:'center'};sheet.getRow(1).height=38;
  const nature=document.order_nature==='INTERNAL'?'内部':'外部';
  sheet.addRow(['编号',document.scheme_no,null,'版本',`V${document.quote_version}`,null,'日期',document.quote_date]);
  sheet.addRow(['订单性质',nature,null,'含税金额',document.total,null,'币种','人民币']);
  sheet.addRow(['买方',document.customer,null,null,'卖方',document.seller.name]);
  sheet.mergeCells('B4:D4');sheet.mergeCells('F4:H4');
  sheet.addRow(['地址','','','','地址',document.seller.address]);sheet.mergeCells('F5:H5');
  sheet.addRow(['电话','','','','电话',document.seller.phone]);
  sheet.addRow(['传真','','','','传真',document.seller.fax]);
  sheet.addRow([]);sheet.addRow(['序号','名称','规格型号(W*D*H)','数量','单位','折后单价','折后总价','备注']);
  for(const row of document.items)sheet.addRow([row.number,row.name,row.specification,row.quantity,row.unit,row.unit_price,row.total,row.remark]);
  sheet.addRow(['','合计','','','','',document.total]);
  sheet.eachRow((row,index)=>{row.height=index>=9?30:26;row.eachCell({includeEmpty:true},cell=>{
    if(index!==1)cell.font={name:'微软雅黑',size:11};
    cell.alignment={vertical:'middle',wrapText:true};
    cell.border={top:{style:'thin',color:{argb:'FFD5E0EF'}},bottom:{style:'thin',color:{argb:'FFD5E0EF'}},left:{style:'thin',color:{argb:'FFD5E0EF'}},right:{style:'thin',color:{argb:'FFD5E0EF'}}};
  });});
  for(let row=10;row<=10+document.items.length;row++)for(const column of [6,7])sheet.getCell(row,column).numFmt='#,##0.00';
  sheet.pageSetup={paperSize:9,orientation:'landscape',fitToPage:true,fitToWidth:1,fitToHeight:0,printTitlesRow:'1:9'};
  return Buffer.from(await workbook.xlsx.writeBuffer());
}
