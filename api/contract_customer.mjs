import {createHash} from 'node:crypto';

// The buyer printed on the frozen quotation is authoritative. Summaries and
// catalogue references from older clients may still describe another buyer.
const clean = value => typeof value === 'string' ? value.trim().normalize('NFC') : '';
const missing = new Set(['', '无', '未选择客户', '请选择客户', '未填写客户']);
export const contractCustomerNameSql = (snapshot='v.snapshot_payload', fallback='s.company_name') => {
  const usable = value => `CASE WHEN btrim(${value}) NOT IN ('','无','未选择客户','请选择客户','未填写客户') THEN btrim(${value}) END`;
  return `COALESCE(${[`${snapshot}->>'company'`, `${snapshot}#>>'{scheme_summary,company}'`, fallback].map(usable).join(',')})`;
};

export function contractCustomer(row) {
  const {catalog_customer_code, snapshot_customer_code, snapshot_customer_name, ...value} = row;
  const name = clean(row.customer_name);
  if (missing.has(name)) throw Object.assign(new Error('正式报价未填写客户名称，请核对所选报价单。'), {statusCode:400});
  const code = clean(catalog_customer_code) || (clean(snapshot_customer_name) === name ? clean(snapshot_customer_code) : '');
  // This is a contract grouping key for a freely typed buyer, not a new entry
  // in the customer catalogue. Never write back or invent a catalogue code.
  return {...value, customer_name:name, customer_code:code ||
    'contract-name:' + createHash('sha256').update(name).digest('hex')};
}
