import assert from "node:assert/strict";
import test from "node:test";

import {
  quickDiscountBreakdown,
  quickDiscountCategory,
} from "./quick_discount_rules.mjs";

test("quick quote discounts only the nine approved attachment categories", () => {
  const approved = [
    ["固定底座", {}, "底座"],
    ["JP侧板", {}, "侧板"],
    ["镀锌安装板", {}, "安装板"],
    ["门板", { category_level1: "内门" }, "内门"],
    ["透明门板", { category_level2: "玻璃门" }, "玻璃门"],
    ["通风顶罩", {}, "通风顶罩"],
    ["防雨顶", {}, "防雨顶"],
    ["分段板", {}, "分段板"],
    ["JK安装板", {}, "JK安装板"],
  ];
  for (const [itemName, metadata, expected] of approved) {
    assert.equal(quickDiscountCategory({ item_name: itemName, ...metadata }), expected);
  }
  for (const itemName of ["风机", "门限位器", "接地线", "文件夹", "三排纵梁", "安装板单发", "JK安装板单发", "运费"]) {
    assert.equal(quickDiscountCategory({ item_name: itemName }), null, itemName);
  }
});

test("quick quote keeps non-approved attachments at original price", () => {
  const attachments = [
    { item_name: "固定底座", quantity: 1, unit_price: 100 },
    { item_name: "内门", quantity: 1, unit_price: 200 },
    { item_name: "风机", quantity: 1, unit_price: 80 },
    { item_name: "接地线", quantity: 2, unit_price: 6 },
  ];
  const result = quickDiscountBreakdown({
    quote: { total_cost: 4406.29, attachment_fee: 392 },
    attachments,
    discount: 0.95,
  });
  assert.equal(result.basePrice, 4014.29);
  assert.equal(result.eligibleAttachmentTotal, 300);
  assert.equal(result.originalPriceAttachmentTotal, 92);
  assert.ok(Math.abs(result.discountedTotal - 4190.5755) < 1e-9);
});

test("door variant surcharge is added after discount exactly once", () => {
  const result = quickDiscountBreakdown({
    quote: {
      total_cost: 1170,
      base_price: 1000,
      attachment_fee: 20,
      door_variant_surcharge: 150,
    },
    attachments: [{ item_name: "接地线", quantity: 1, unit_price: 20 }],
    discount: 0.9,
  });
  assert.equal(result.doorVariantSurcharge, 150);
  assert.equal(result.discountedTotal, 1070);
});
