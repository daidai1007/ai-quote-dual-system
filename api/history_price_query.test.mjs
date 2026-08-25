import assert from 'node:assert/strict';
import test from 'node:test';

import {
  historyPriceMatchSql,
  normalizeHistoryPriceMatchInput,
} from './history_price_query.mjs';

test('history price lookup requires three exact visible selections', () => {
  assert.deepEqual(normalizeHistoryPriceMatchInput({
    company_name: ' 浙江万丰科技开发股份有限公司 ',
    specification: '1000*600*(1800+200)',
    cabinet_type: 'JS独立式控制柜',
  }), {
    company_name: '浙江万丰科技开发股份有限公司',
    specification: '1000*600*(1800+200)',
    cabinet_type: 'JS独立式控制柜',
  });
  assert.throws(
    () => normalizeHistoryPriceMatchInput({ company_name: '客户', specification: '1000*600*1800' }),
    /cabinet_type is required/,
  );
});

test('history price SQL only returns contract and tax-included price evidence', () => {
  const sql = historyPriceMatchSql({
    company_name: "客户' OR TRUE --",
    specification: '1000*600*(1800+200)',
    cabinet_type: 'JS独立式控制柜',
  });

  assert.match(sql, /FROM calc\."历史价格" h/);
  assert.match(sql, /h\.customer_name = convert_from\(decode\('/);
  assert.match(sql, /h\.specification = convert_from\(decode\('/);
  assert.match(sql, /h\.cabinet_type = convert_from\(decode\('/);
  assert.match(sql, /GROUP BY dingtalk_contract_no, tax_included_unit_price/);
  assert.match(sql, /LIMIT 50/);
  assert.doesNotMatch(sql, /OR TRUE/);
  assert.doesNotMatch(sql, /formula_cost|quick_quote|UPDATE|DELETE|INSERT/);
});
