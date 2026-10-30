// Named colleagues may borrow a configured template when their customer has
// none. Customer identity and quote/ledger values never come from the template.
const clean=value=>String(value??'').trim().normalize('NFC');
export const templateMatchesCustomer=(template,customer)=>customer.customer_key
  ? clean(template.customer_name)===clean(customer.customer_name)
  : template.customer_code===customer.customer_code;
export const hasBuyerMapping=mapping=>(mapping?.fields||[]).some(field=>field.source==='buyer_name');
export const buyerMappingSql=alias=>`EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(${alias}.field_mapping->'fields','[]'::jsonb)) buyer_field WHERE buyer_field->>'source'='buyer_name')`;
export const ledgerMappingSql=alias=>`COALESCE((${alias}.field_mapping#>'{items,columns}') ?& ARRAY['name','specification','quantity','unit','unit_price','total','remark'],FALSE)`;

export function createContractTemplatePolicy({query,q}) {
  const matching=(customer,alias)=>customer.customer_key
    ? `btrim(${alias}.customer_name)=${q(clean(customer.customer_name))}`
    : `${alias}.customer_code=${q(customer.customer_code)}`;
  const ownAvailable=customer=>`EXISTS(SELECT 1 FROM calc.contract_template_group own_g
    ${customer.customer_key?'JOIN calc.contract_template_version own_v ON own_v.group_id=own_g.group_id':`JOIN LATERAL(SELECT field_mapping FROM calc.contract_template_version own_version
      WHERE own_version.group_id=own_g.group_id ORDER BY version_no DESC LIMIT 1) own_v ON TRUE`}
    WHERE own_g.enabled AND own_v.field_mapping IS NOT NULL AND ${matching(customer,'own_g')}${customer.customer_key?' AND '+ledgerMappingSql('own_v'):''})`;
  return {
    allowedSql(customer,alias='g') {return `(${matching(customer,alias)} OR NOT ${ownAvailable(customer)})`;},
    async validate(customer,template) {
      if(!template.enabled||!template.field_mapping)
        throw Object.assign(new Error('模板尚未配置或已停用'),{statusCode:400});
      if(templateMatchesCustomer(template,customer))return false;
      if(await query(`SELECT to_jsonb(${ownAvailable(customer)}) AS matching_customer_template;`))
        throw Object.assign(new Error((customer.customer_key?'合同模板与台账客户不一致':'客户模板与正式报价客户不一致')+'：当前客户已有可用模板，请优先使用对应模板。'),{statusCode:400});
      if(!hasBuyerMapping(template.field_mapping))
        throw Object.assign(new Error('借用模板需要配置需方名称的填入位置，请先配置模板。'),{statusCode:400});
      return true;
    },
  };
}
