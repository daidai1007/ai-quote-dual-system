const positivePrice=(value,label)=>{
  const number=Number(value);
  if(!Number.isFinite(number)||number<=0||number>1e5) throw new Error(`${label}必须由成本计算副导航栏提供有效正数`);
  return number;
};

const codeOf=value=>String(value||'').trim().toUpperCase();
const galvanizedCodes=new Set(['SGCC','DX51D','GI']);

export function materialUnitPriceFromSidebar(input,materialCode){
  const code=codeOf(materialCode);
  if(galvanizedCodes.has(code)){
    return positivePrice(input.galvanized_sheet_unit_price_override,'镀锌板价格');
  }
  const selectedPrice=input.material_unit_price_override??input.carbon_steel_unit_price_override;
  if(code===codeOf(input.material_code)) return positivePrice(selectedPrice,'当前材质价格');
  // Transitional compatibility for catalogs not yet migrated from the old
  // fixed-SECC marker.  Once fixed rows are SGCC they take the branch above.
  if(code==='SECC') return positivePrice(input.galvanized_sheet_unit_price_override,'镀锌板价格');
  throw new Error(`材质 ${code} 既不是当前识别材质，也不是固定镀锌板`);
}

export function withSidebarMaterialPrices(input,materials){
  const selected=codeOf(input.material_code);
  return (materials||[]).map(material=>{
    const code=codeOf(material.material_code);
    const relevant=code===selected||galvanizedCodes.has(code)||(code==='SECC'&&selected!=='SECC');
    return relevant?{...material,material_unit_price:materialUnitPriceFromSidebar(input,code),
      quote_local_price_override:true}:material;
  });
}
