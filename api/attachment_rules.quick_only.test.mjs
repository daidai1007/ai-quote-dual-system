import assert from "node:assert/strict";
import {
  QUICK_ONLY_ATTACHMENT_PRICES,
  calculateQuickOnlyAttachmentFee,
  applyQuickOnlyAttachmentRuleToQuoteRow,
  splitAttachmentFees,
} from "./attachment_rules.mjs";

const five = [
  { name: "JA、JE单开门改为双开门", quantity: 1 },
  { name: "JS、JP单门改为上下门", quantity: 1 },
  { name: "JS、JP单门改为双开门", quantity: 1 },
  { name: "JS、JP后背板改为单开门", quantity: 1 },
  { name: "JS、JP后背板改为双开门", quantity: 1 },
];

assert.equal(Object.keys(QUICK_ONLY_ATTACHMENT_PRICES).length, 5);
assert.equal(calculateQuickOnlyAttachmentFee(five), 750);
for (const item of five) {
  const expected = Object.entries(QUICK_ONLY_ATTACHMENT_PRICES)
    .find(([name]) => name === item.name.replaceAll("、", "").replaceAll("单开门", "单门").replaceAll("双开门", "双门"))?.[1];
  assert.equal(calculateQuickOnlyAttachmentFee([item]), expected, item.name);
}

assert.equal(calculateQuickOnlyAttachmentFee([
  { name: "JS、JP单开门改为双开门", quantity: 2, unit_price_override: 77 },
]), 154);

const adjusted = applyQuickOnlyAttachmentRuleToQuoteRow({
  formula_attachment_fee: 800,
  formula_total_cost: 3000,
  formula_cost: { attachment_fee: 800, total_cost: 3000 },
  quick_total_cost: 4000,
}, five);
assert.equal(adjusted.formula_attachment_fee, 50);
assert.equal(adjusted.formula_total_cost, 2250);
assert.equal(adjusted.formula_cost.attachment_fee, 50);
assert.equal(adjusted.formula_cost.total_cost, 2250);
assert.equal(adjusted.quick_total_cost, 4000);
assert.equal(adjusted.attachment_billing_rules.quick_only_attachment_fee, 750);

const ordinary = [{ name: "安装板", quantity: 2, unit_price: 30 }, five[0]];
const split = splitAttachmentFees(ordinary);
assert.equal(split.formulaFee, 60);
assert.equal(split.quickOnlyFee, 60);
assert.equal(split.quickFee, 120);

const overridden = splitAttachmentFees([
  { name: "安装板", quantity: 3, unit_price_override: 20 },
  { name: "JS、JP单开门改为双开门", quantity: 2, unit_price_override: 77 },
]);
assert.deepEqual(overridden, { formulaFee: 60, quickOnlyFee: 154, quickFee: 214 });

const twice = applyQuickOnlyAttachmentRuleToQuoteRow(adjusted, five);
assert.deepEqual(twice, adjusted);

console.log("attachment quick-only regression passed");
