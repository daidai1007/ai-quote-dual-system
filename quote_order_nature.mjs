/** Classification is document metadata, never an input to price calculations. */
export const ORDER_NATURES = Object.freeze(['INTERNAL', 'EXTERNAL', 'UNCLASSIFIED']);
export const orderNature = value => ORDER_NATURES.includes(value) ? value : 'UNCLASSIFIED';
export const orderNatureLabel = value => ({INTERNAL:'内部',EXTERNAL:'外部',UNCLASSIFIED:'待分类'})[orderNature(value)];
const fail = message => Object.assign(new Error(message), {statusCode:400});
export const validateOrderNature = (value, required=false) => {
  if (value != null && value !== '' && !ORDER_NATURES.includes(value)) throw fail('订单性质无效，请选择内部或外部。');
  const result = orderNature(value);
  if (required && result === 'UNCLASSIFIED') throw fail('请先选择订单性质（内部或外部），再打印或导出。');
  return result;
};
export const snapshotOrderNature = snapshot => orderNature(snapshot?.document?.order_nature);
export const snapshotWithOrderNature = (snapshot, required=false) => {
  const nature = validateOrderNature(snapshot?.document?.order_nature, required);
  const result = {...snapshot, document:{...snapshot.document, order_nature:nature}};
  const management = snapshot?.quote_management;
  const current = management?.versions?.find(v => v.version === management.current);
  if (current && current.order_nature != null && validateOrderNature(current.order_nature) !== nature)
    throw fail('报价版本与订单性质不一致，请重新打开后核对。');
  return result;
};
export const documentWithOrderNature = (payload, required=false) => {
  const values = new Set((Array.isArray(payload?.items) ? payload.items : []).map(item => item?.quote_order_nature).filter(v => v != null));
  if (payload.order_nature != null) values.add(payload.order_nature);
  if (values.size > 1) throw fail('报价明细的订单性质不一致，请重新核对。');
  const nature = validateOrderNature([...values][0], required);
  return {...payload, order_nature:nature};
};
// Only use with trusted SQL expressions, never user-supplied identifiers.
export const orderNatureSql = payload => `(CASE WHEN ${payload}#>>'{document,order_nature}' IN ('INTERNAL','EXTERNAL') THEN ${payload}#>>'{document,order_nature}' ELSE 'UNCLASSIFIED' END)`;
