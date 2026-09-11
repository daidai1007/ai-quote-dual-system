// Layout only: no formula evaluation, price lookup or name-based joins.
export function addAttachmentSnapshotSheet(workbook, payload) {
  const items=payload.items||[];
  if(!items.some(item=>item.attachment_contract===2)) return;
  const sheet=workbook.addWorksheet('附件双报价明细');
  const headers=['报价行ID','附件选择ID','产品名称','一级分类','二级分类','附件名称','型号','单位','选择数量','加减符号',
    '面价（元/单位）','快速金额（元/选择行）','材料重量（kg/单位）','材料单价（元/kg）','材料成本（元/单位）',
    '喷塑面积（m²/单位）','喷塑单价（元/m²）','喷塑成本（元/单位）','辅材成本（元/单位）','辅材清单',
    '人工（元/单位）','公式单位成本（元/单位）','公式金额（元/选择行）','人工输入尺寸（mm）','状态','计算说明',
    '材质','密度（g/cm³）','报价日期','规则ID','规则版本'];
  sheet.addRow(headers);
  for(const item of items){
    if(item.attachment_contract!==2) continue;
    for(const row of item.attachments||[]){
      if(!item.quote_line_id||!row.attachment_selection_id||row.quote_line_id!==item.quote_line_id) throw new Error('附件导出缺少准确的报价行/选择ID关联');
      if(row.status==='ERROR') throw new Error(`${row.item_name}：${row.error||'附件计算错误'}`);
      const env=row.environment||{};
      const explanation=[row.status==='FIXED'?'固定成本：组成项未拆分':row.calculation_notes,
        '数量为所属产品的一次选择数量；单位组成未乘选择数量；金额已乘选择数量及符号；订单柜体数量按原有报价规则处理。',
        row.formulas?JSON.stringify(row.formulas):''].filter(Boolean).join('\n');
      const values=[item.quote_line_id,row.attachment_selection_id,item.name||item.model_code,row.category_level1,row.category_level2,row.item_name,row.model_code,row.unit,row.quantity,row.attachment_price_sign,
        row.face_price,row.quick_amount,row.weight_kg,env.material_unit_price,row.material_cost,row.spray_area_m2,env.spray_unit_price,row.spray_cost,row.auxiliary_cost,row.auxiliary_list,
        row.labor_cost,row.formula_unit_cost,row.formula_amount,JSON.stringify(row.manual_inputs||{}),row.status==='QUICK_ONLY'?'仅快速报价':row.status_text,explanation,
        env.material_code,env.density_g_cm3,env.quote_date,row.rule_id,row.rule_version];
      sheet.addRow(values.map(value=>value??null));
    }
  }
  sheet.views=[{state:'frozen',xSplit:3,ySplit:1}];
  sheet.autoFilter={from:{row:1,column:1},to:{row:sheet.rowCount,column:headers.length}};
  sheet.columns.forEach((column,i)=>{column.width=[0,1].includes(i)?38:[19,23,25].includes(i)?48:19;});
  sheet.getRow(1).font={bold:true};
  sheet.getRow(1).height=42;
  sheet.eachRow((row,index)=>{
    row.alignment={vertical:'top',wrapText:true};
    if(index>1) row.height=Math.min(240,Math.max(48,String(row.getCell(20).value||'').split('\n').length*15));
    if(index>1) {
      for(const column of [11,13,14,15,16,17,18,19,21,22,28]) row.getCell(column).numFmt='0.######';
      for(const column of [12,23]) row.getCell(column).numFmt='0.00';
    }
  });
}
