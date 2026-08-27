import assert from "node:assert/strict";
import test from "node:test";

import {
  effectiveAttachmentQuantity,
  quickDiscountBreakdown,
  quickDiscountCategory,
  quickOrderLineBreakdown,
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
  for (const itemName of ["风机", "门限位器", "接地线", "铜排", "文件夹", "三排纵梁", "安装板单发", "JK安装板单发", "运费"]) {
    assert.equal(quickDiscountCategory({ item_name: itemName }), null, itemName);
  }
});

test("copper busbar stays at original price and scales with cabinet and ganged counts", () => {
  const copper = {
    item_name: "铜排",
    category_level1: "铜排",
    quantity: 1,
    unit_price: 50,
  };
  assert.equal(quickDiscountCategory(copper), null);
  assert.equal(effectiveAttachmentQuantity(copper, 2, 3), 6);
  const result = quickOrderLineBreakdown({
    quote: { base_price: 1000, attachment_fee: 50, total_cost: 1050 },
    attachments: [copper],
    discount: 0.9,
    cabinetQuantity: 2,
    gangedCabinetCount: 3,
  });
  assert.equal(result.eligibleAttachmentTotal, 0);
  assert.equal(result.originalPriceAttachmentTotal, 300);
  assert.equal(result.lineTotal, 2100);
  assert.equal(result.equivalentUnitTotal, 1050);
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

test("negative installation board remains in the discount base", () => {
  const result = quickDiscountBreakdown({
    quote: {
      total_cost: 900,
      base_price: 1000,
      attachment_fee: -100,
    },
    attachments: [{
      item_name: "安装板",
      category_level1: "安装板",
      quantity: 1,
      unit_price: 100,
      attachment_price_sign: -1,
    }],
    discount: 0.9,
  });
  assert.equal(result.listedAttachmentTotal, -100);
  assert.equal(result.eligibleAttachmentTotal, -100);
  assert.equal(result.originalPriceAttachmentTotal, 0);
  assert.equal(result.discountedTotal, 810);
});

test("cabinet quantity multiplies normal attachments but not the three manual categories", () => {
  assert.equal(effectiveAttachmentQuantity({ item_name: "门限位器", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "安装板", quantity: 1 }, 3), 3);
  assert.equal(effectiveAttachmentQuantity({ item_name: "铜排", category_level1: "铜排", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "侧板", quantity: 2 }, 3), 2);
  assert.equal(effectiveAttachmentQuantity({ item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1 }, 3), 1);
  assert.equal(effectiveAttachmentQuantity({ item_name: "KA2206风机", quantity: 2 }, 3), 2);
  assert.equal(effectiveAttachmentQuantity({ item_name: "FU滤网", quantity: 2 }, 3), 2);
});

test("ganged cabinet count multiplies normal attachments in addition to order quantity", () => {
  assert.equal(effectiveAttachmentQuantity({ item_name: "门限位器", quantity: 2 }, 3, 4), 24);
  assert.equal(effectiveAttachmentQuantity({ item_name: "安装板", quantity: 1 }, 2, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "铜排", category_level1: "铜排", quantity: 2 }, 2, 3), 12);
  assert.equal(effectiveAttachmentQuantity({ item_name: "侧板", quantity: 2 }, 3, 4), 2);
  assert.equal(effectiveAttachmentQuantity({ item_name: "门变形", category_level1: "门变形", quantity: 1 }, 3, 4), 1);
  assert.equal(effectiveAttachmentQuantity({ item_name: "风机", category_level1: "风机滤网", quantity: 2 }, 3, 4), 2);
});

test("quick order line applies quantity exceptions and scales negative boards once", () => {
  const attachments = [
    { item_name: "安装板", category_level1: "安装板", quantity: 1, unit_price: 100, attachment_price_sign: -1 },
    { item_name: "侧板", category_level1: "侧板", quantity: 2, unit_price: 50 },
    { item_name: "KA2206风机", category_level1: "风机滤网", quantity: 1, unit_price: 30 },
    { item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1, unit_price: 150 },
  ];
  const result = quickOrderLineBreakdown({
    quote: { base_price: 1000, attachment_fee: 180, total_cost: 1180 },
    attachments,
    discount: 0.9,
    cabinetQuantity: 3,
  });
  // Discounted: cabinet 3000 - installation board 300 + side panels 100.
  // Original price: fan 30 + door transformation 150.
  assert.equal(result.eligibleAttachmentTotal, -200);
  assert.equal(result.originalPriceAttachmentTotal, 180);
  assert.equal(result.lineTotal, 2700);
  assert.equal(result.equivalentUnitTotal, 900);
});

test("quick order line combines ganged and order multipliers without scaling exceptions", () => {
  const attachments = [
    { item_name: "安装板", category_level1: "安装板", quantity: 1, unit_price: 100, attachment_price_sign: -1 },
    { item_name: "侧板", category_level1: "侧板", quantity: 2, unit_price: 50 },
    { item_name: "风机", category_level1: "风机滤网", quantity: 1, unit_price: 30 },
    { item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1, unit_price: 150 },
  ];
  const result = quickOrderLineBreakdown({
    quote: { base_price: 2000, attachment_fee: 180, total_cost: 2180 },
    attachments,
    discount: 0.9,
    cabinetQuantity: 2,
    gangedCabinetCount: 3,
  });
  assert.equal(result.eligibleAttachmentTotal, -500);
  assert.equal(result.originalPriceAttachmentTotal, 180);
  assert.equal(result.lineTotal, 3330);
  assert.equal(result.equivalentUnitTotal, 1665);
});
