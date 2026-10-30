import {money,moneySum,moneyProduct,formulaAttachmentLineAmount,formulaAttachmentExcluded,attachmentExcludedFromDiscount,hasManufacturingCost} from '../quick_discount_rules.mjs';
const required=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
import {hasTaxCost} from '../tax_cost.mjs';
export function upperRmb(value){
  const cents=Math.round(money(value)*100);if(!Number.isSafeInteger(cents)||cents<0||cents>=1e14)throw Error('合同金额超出大写转换范围');
  const digits='零壹贰叁肆伍陆柒捌玖',small=['','拾','佰','仟'],big=['','万','亿'];
  const group=n=>{let s='',zero=false;for(let i=3;i>=0;i--){const d=Math.floor(n/10**i)%10;if(d){if(zero&&s)s+='零';s+=digits[d]+small[i];zero=false;}else if(s)zero=true;}return s;};
  let whole=Math.floor(cents/100),text='',zero=false;for(let i=2;i>=0;i--){const g=Math.floor(whole/10000**i)%10000;if(g){if(text&&(zero||g<1000))text+='零';text+=group(g)+big[i];zero=false;}else if(text)zero=true;}
  text=(text||'零')+'元';const j=Math.floor(cents/10)%10,f=cents%10;if(!j&&!f)return text+'整';if(j)text+=digits[j]+'角';else if(f&&whole)text+='零';if(f)text+=digits[f]+'分';return text;
}
export function contractQuote(snapshot,method){
  if(!['QUICK','FORMULA'].includes(method))throw Error('请选择合同采用的报价方式');
  const frozen=snapshot?.contract_quote_snapshot;
  if(frozen&&frozen.schema!==1)throw Error('正式报价合同快照格式不支持，请更新客户端');
  const source=frozen?.items||snapshot?.draft_items;if(!Array.isArray(source)||!source.length)throw Error('正式报价没有产品明细');
  const items=source.map((item,i)=>{
    const display=item.quote_display;if(!display)throw Error(`第${i+1}行缺少正式报价显示快照，请重新确认对应报价版本`);
    const quantity=Number(display.quantity);if(!Number.isInteger(quantity)||quantity<1)throw Error('正式报价数量无效');
    let unit_price,total;
    if(method==='QUICK'){if(!required(display.unit_price)||!required(display.total))throw Error('快速报价金额未确定');unit_price=money(display.unit_price);total=money(display.total);}
    else if(required(display.formula_unit_price)&&required(display.formula_total)){unit_price=money(display.formula_unit_price);total=money(display.formula_total);}
    else{
      const costs=item.formula||{},keys=['material_cost','auxiliary_cost','labor_cost','spray_cost','management_fee'];
      if(hasManufacturingCost(item))keys.push('manufacturing_cost');
      if(hasTaxCost(item))keys.push('tax_cost');
      if(keys.some(k=>!required(costs[k])))throw Error('该正式快照的公式成本不完整，请先确认并导出对应版本');
      const attachments=display.attachment_source==='popup_v1'?display.attachments||[]:item.attachments||[];
      if(attachments.some(a=>a.status==='ERROR'))throw Error('正式附件金额未确定');
      const included=attachments.filter(a=>!formulaAttachmentExcluded(a));
      const factor=Number(item.formula_discount??1),freight=Number(item.freight_fee??item.freight??0);
      if(!Number.isFinite(factor)||!Number.isFinite(freight))throw Error('正式公式报价系数无效');
      // The same per-unit formula as the formal workbook. All inputs are from
      // the immutable snapshot; no catalogue, new management rate or repricing.
      unit_price=moneySum([moneyProduct(moneySum([...keys.map(k=>costs[k]),...included.filter(a=>!attachmentExcludedFromDiscount(a)).map(formulaAttachmentLineAmount)]),factor),...included.filter(attachmentExcludedFromDiscount).map(formulaAttachmentLineAmount),Math.max(0,freight)]);
      total=moneyProduct(unit_price,quantity);
    }
    if(unit_price<0||total<0||moneyProduct(unit_price,quantity)!==total)throw Error('正式报价单价、数量与行金额不一致');
    return {number:i+1,name:String(display.name||item.name||item.product_code||''),specification:String(display.specification||item.specification||''),quantity,unit:String(display.unit||'台'),unit_price,total,remark:String(display.remark||'')};
  });
  const total=moneySum(items.map(i=>i.total));return {items,total,total_upper:upperRmb(total)};
}
