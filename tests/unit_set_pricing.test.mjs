import assert from 'node:assert/strict';
import test from 'node:test';
import * as pricing from '../quick_discount_rules.mjs';
import {calculateAttachment} from '../api/attachment_cost.mjs';

test('half-up money handles ties and negative deductions without binary drift', () => {
  for (const [input, expected] of [['1.005', 1.01], ['-1.005', -1.01], ['2.675', 2.68], ['1e-3', 0]]) {
    assert.equal(pricing.money(input), expected);
  }
  assert.equal(pricing.moneyProduct('0.1', 3), .3);
  assert.equal(pricing.moneySum([.1, .2]), .3);
});

test('current row money wins over stale catalogue prices, including manual zero', () => {
  assert.equal(pricing.quickAttachmentLineAmount({quantity: 1, matched_price: 10, quick_amount: 12}), 12);
  assert.equal(pricing.quickAttachmentLineAmount({quantity: 1, quick_amount: 12,
    quick_amount_override: 0, custom_amount_edited: true}), 0);
  assert.equal(pricing.quickAttachmentLineAmount({quantity: 1, quick_amount: 12,
    quick_amount_override: 99, custom_amount_edited: false}), 12);
});

test('manual and automatic rows both represent a complete unit or ganged set', () => {
  for (const source of ['manual', 'QUOTE_LOCAL', 'automatic']) {
    assert.equal(pricing.effectiveAttachmentQuantity({quantity: 2, selection_source: source}, 3, 4), 6);
  }
});

test('round unit quote first, multiply order quantity last', () => {
  const result = pricing.quickOrderLineBreakdown({quote: {base_price: 12.34}, discount: .1, cabinetQuantity: 10});
  assert.equal(result.equivalentUnitTotal, 1.23);
  assert.equal(result.lineTotal, 12.3);
});

test('freight and material surcharge are added once outside the discount', () => {
  const result = pricing.quickOrderLineBreakdown({quote: {base_price: 100},
    attachments: [{item_name: '安装板', quick_amount: 12}, {item_name: '铜排', quick_amount: 15}],
    discount: .5, freightFee: 3, materialDifference: 2, cabinetQuantity: 10, gangedCabinetCount: 3});
  assert.equal(result.equivalentUnitTotal, 76);
  assert.equal(result.lineTotal, 760);
});

test('new snapshot prices and costs are rounded before attachment quantity is applied', () => {
  const row=calculateAttachment({quantity:10},
    {attachment_price_id:1,item_name:'并柜件',price:1.005,data_version:'test'},
    [{rule_id:1,method:'FIXED',fixed_cost:1.005}],
    {product_code:'JP',material_code:'SECC',pricing_basis:pricing.PRICING_BASIS});
  assert.equal(row.quick_amount,10.1);
  assert.equal(row.matched_price,1.01);
  assert.equal(row.formula_amount,10.1);
});

test('frozen displays validate rounded unit totals, zero discount, surcharge and legacy contracts', () => {
  const item={pricing_basis:pricing.PRICING_BASIS, quantity:10, quick_discount:0,
    material_code:'SUS316', freight_fee:3, scheme2_cost_settings:{material_difference:25},
    formula:{corrected_material_weight_kg:3, material_details:[{material_code:'SGCC',billable_weight_kg:1}]},
    quick:{base_price:100,attachment_fee:20,total_cost:120},
    attachments:[{item_name:'填充安装板',quantity:1,quick_amount:20}],
    quote_display:{quantity:10,discount:0,unit_price:73,total:730,attachment_face_price:20,
      material_difference:50,quick_base_price:100,quick_attachment_fee:20,quick_total_cost:120}};
  assert.doesNotThrow(()=>pricing.validateQuoteDisplay(item));
  assert.throws(()=>pricing.validateQuoteDisplay({...item,quote_display:{...item.quote_display,total:731}}),/total/);
  assert.throws(()=>pricing.validateQuoteDisplay({...item,quote_display:{...item.quote_display,unit_price:73.001}}),/unit_price/);
  assert.throws(()=>pricing.validateQuoteDisplay({...item,pricing_basis:'unknown'}),/更新客户端/);
  assert.doesNotThrow(()=>pricing.validateQuoteDisplay({quantity:10}));
});
