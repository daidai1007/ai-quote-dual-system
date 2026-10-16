import assert from "node:assert/strict";
import test from "node:test";

import {
  effectiveAttachmentLineAmount,
  effectiveAttachmentQuantity,
  attachmentExcludedFromDiscount,
  formulaAttachmentExcluded,
  quickAttachmentLineAmount,
  quickDiscountBreakdown,
  quickDiscountCategory,
  quickOrderLineBreakdown,
} from "./quick_discount_rules.mjs";

test("formula-only exclusion uses the exact first-level door-transformation category", () => {
  assert.equal(formulaAttachmentExcluded({
    category_level1: "门变形",
    category_level2: "JS、JP后背板改为单开门",
    item_name: "JS、JP后背板改为单开门",
  }), true);
  assert.equal(formulaAttachmentExcluded({
    category_level1: "其他附件",
    item_name: "人工门变形补差",
  }), false);
  assert.equal(formulaAttachmentExcluded({
    category_level1: "配置变形",
    category_level2: "门变形",
    item_name: "门变形",
  }), false);
});

test("missing numeric quote fields and attachment quantities keep fallback semantics", () => {
  const attachment = { item_name: "固定底座", quantity: null, unit_price: 100 };
  assert.equal(quickAttachmentLineAmount(attachment), 100);
  assert.equal(effectiveAttachmentQuantity(attachment, null, null), 1);
  assert.equal(effectiveAttachmentLineAmount(attachment, null, null), 100);

  const result = quickDiscountBreakdown({
    quote: { total_cost: 1100, base_price: null, attachment_fee: null },
    attachments: [attachment],
    discount: 0.9,
  });
  assert.equal(result.attachmentFee, 100);
  assert.equal(result.basePrice, 1000);
  assert.equal(result.discountedTotal, 990);
});

test("an explicit zero attachment quantity remains a zero amount", () => {
  const attachment = { item_name: "固定底座", quantity: 0, unit_price: 100 };
  assert.equal(quickAttachmentLineAmount(attachment), 0);
  assert.equal(effectiveAttachmentQuantity(attachment, 2, 3), 0);
  assert.equal(effectiveAttachmentLineAmount(attachment, 2, 3), 0);
});

test("quick quote discounts only the eleven approved attachment categories", () => {
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
    ["无孔承板", {}, "无孔承板"],
    ["有孔承板", {}, "有孔承板"],
  ];
  for (const [itemName, metadata, expected] of approved) {
    assert.equal(quickDiscountCategory({ item_name: itemName, ...metadata }), expected);
  }
  for (const itemName of ["风机", "门限位器", "接地线", "铜排", "文件夹", "三排纵梁", "门安装条", "安装板单发", "JK安装板单发", "运费"]) {
    assert.equal(quickDiscountCategory({ item_name: itemName }), null, itemName);
  }
  assert.equal(attachmentExcludedFromDiscount({ category_level1: "门安装条" }), true);
  assert.equal(attachmentExcludedFromDiscount({ item_name: "安装板" }), false);
  const otherAttachmentNamedLikeEligible = {
    category_level1: "其他附件",
    item_name: "侧板",
  };
  assert.equal(quickDiscountCategory(otherAttachmentNamedLikeEligible), null);
  assert.equal(attachmentExcludedFromDiscount(otherAttachmentNamedLikeEligible), true);
});

test("perforated and solid support plates enter the quick discount base", () => {
  const result = quickDiscountBreakdown({
    quote: { base_price: 1000, attachment_fee: 300, total_cost: 1300 },
    attachments: [
      { item_name: "有孔承板", category_level1: "控制柜附件", quantity: 1, unit_price: 100 },
      { item_name: "无孔承板", category_level1: "控制柜附件", quantity: 1, unit_price: 200 },
    ],
    discount: 0.8,
  });
  assert.equal(result.eligibleAttachmentTotal, 300);
  assert.equal(result.originalPriceAttachmentTotal, 0);
  assert.equal(result.discountedTotal, 1040);
});

test("filling installation board remains at original price for every identity field", () => {
  for (const key of ["item_name", "category_level1", "category_level2", "category_level3",
    "attachment_category", "category", "model_code"]) {
    const row = { item_name: "安装板", category_level1: "安装板", [key]: " 填充安装板 " };
    assert.equal(quickDiscountCategory(row), null, key);
    assert.equal(attachmentExcludedFromDiscount(row), true, key);
  }
  for (const item_name of ["安装板", "JK安装板", "填充板", "填充安装板固定件"]) {
    assert.ok(quickDiscountCategory({ item_name }), item_name);
    assert.equal(attachmentExcludedFromDiscount({ item_name }), false, item_name);
  }
});

test("filling installation board preserves amount, quantity, deduction and cost without changing other discounts", () => {
  for (const sign of [1, -1]) {
    const fill = { item_name: "填充安装板", category_level1: "配置变形", quantity: 2,
      catalog_version: "offline", quick_amount: 200 * sign, formula_amount: 120 * sign,
      attachment_price_sign: sign };
    const attachments = [fill, { item_name: "安装板", quantity: 1, unit_price: 100 },
      { item_name: "风机", quantity: 1, unit_price: 50 }];
    const before = structuredClone(attachments);
    const quote = { base_price: 1000, attachment_fee: 150 + 200 * sign,
      total_cost: 1150 + 200 * sign };
    const unit = quickDiscountBreakdown({ quote, attachments, discount: .5 });
    assert.equal(unit.eligibleAttachmentTotal, 100);
    assert.equal(unit.originalPriceAttachmentTotal, 50 + 200 * sign);
    assert.equal(unit.discountedTotal, 600 + 200 * sign);
    const order = quickOrderLineBreakdown({ quote, attachments, discount: .5,
      cabinetQuantity: 3, gangedCabinetCount: 2, freightFee: 10 });
    assert.equal(order.lineTotal, (600 + 200 * sign) * 3 + 30);
    assert.deepEqual(attachments, before);
  }
});

test("other attachments remain at original price in both quotation methods", () => {
  const attachments = [
    { item_name: "侧门", category_level1: "其他附件", quantity: 1, unit_price: 150 },
    { item_name: "隔板", category_level1: "其他附件", quantity: 1, unit_price: 60 },
  ];
  const unit = quickDiscountBreakdown({
    quote: { base_price: 1000, attachment_fee: 210, total_cost: 1210 },
    attachments,
    discount: 0.8,
  });
  assert.equal(unit.eligibleAttachmentTotal, 0);
  assert.equal(unit.originalPriceAttachmentTotal, 210);
  assert.equal(unit.discountedTotal, 1010);
  assert.equal(attachments.every(attachmentExcludedFromDiscount), true);
});

test("door installation strip remains at original price in quick quote", () => {
  const strip = {
    item_name: "门安装条",
    category_level1: "门安装条",
    quantity: 1,
    unit_price: 20,
  };
  const unit = quickDiscountBreakdown({
    quote: { base_price: 1000, attachment_fee: 20, total_cost: 1020 },
    attachments: [strip],
    discount: 0.8,
  });
  assert.equal(unit.eligibleAttachmentTotal, 0);
  assert.equal(unit.originalPriceAttachmentTotal, 20);
  assert.equal(unit.discountedTotal, 820);

  const order = quickOrderLineBreakdown({
    quote: { base_price: 1000, attachment_fee: 20, total_cost: 1020 },
    attachments: [strip],
    discount: 0.8,
    cabinetQuantity: 3,
  });
  assert.equal(order.originalPriceAttachmentTotal, 60);
  assert.equal(order.lineTotal, 2460);
});

test("copper busbar stays at original price and scales only with complete ganged sets", () => {
  const copper = {
    item_name: "铜排",
    category_level1: "铜排",
    quantity: 1,
    unit_price: 50,
  };
  assert.equal(quickDiscountCategory(copper), null);
  assert.equal(effectiveAttachmentQuantity(copper, 2, 3), 2);
  const result = quickOrderLineBreakdown({
    quote: { base_price: 1000, attachment_fee: 50, total_cost: 1050 },
    attachments: [copper],
    discount: 0.9,
    cabinetQuantity: 2,
    gangedCabinetCount: 3,
  });
  assert.equal(result.eligibleAttachmentTotal, 0);
  assert.equal(result.originalPriceAttachmentTotal, 100);
  assert.equal(result.lineTotal, 1900);
  assert.equal(result.equivalentUnitTotal, 950);
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
  assert.equal(result.discountedTotal, 4190.58);
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

test("cabinet quantity multiplies every ordinary attachment row", () => {
  assert.equal(effectiveAttachmentQuantity({ item_name: "门限位器", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "安装板", quantity: 1 }, 3), 3);
  assert.equal(effectiveAttachmentQuantity({ item_name: "铜排", category_level1: "铜排", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "侧板", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "JS、JP后背板改为单开门", category_level1: "门变形", quantity: 1 }, 3), 3);
  assert.equal(effectiveAttachmentQuantity({ item_name: "KA2206风机", quantity: 2 }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "FU滤网", quantity: 2 }, 3), 6);
});

test("identical cabinet lines scale linearly with order quantity", () => {
  const attachments = [
    { item_name: "固定底座", quantity: 1, unit_price: 100 },
    { item_name: "风机", category_level1: "风机滤网", quantity: 1, unit_price: 50 },
  ];
  const quote = { base_price: 3000, attachment_fee: 150, total_cost: 3150 };
  const one = quickOrderLineBreakdown({
    quote, attachments, discount: 0.5, cabinetQuantity: 1,
  });
  const ten = quickOrderLineBreakdown({
    quote, attachments, discount: 0.5, cabinetQuantity: 10,
  });
  assert.equal(ten.lineTotal, one.lineTotal * 10);
  assert.equal(ten.equivalentUnitTotal, one.equivalentUnitTotal);
});

test("ganged attachments use selected quantity times complete-set quantity only", () => {
  assert.equal(effectiveAttachmentQuantity({ item_name: "门限位器", quantity: 7 }, 3, 4), 21);
  assert.equal(effectiveAttachmentQuantity({ item_name: "安装板", quantity: 1 }, 2, 3), 2);
  assert.equal(effectiveAttachmentQuantity({ item_name: "铜排", category_level1: "铜排", quantity: 2 }, 2, 3), 4);
  assert.equal(effectiveAttachmentQuantity({ item_name: "侧板", quantity: 2 }, 3, 4), 6);
  assert.equal(effectiveAttachmentQuantity({ item_name: "门变形", category_level1: "门变形", quantity: 1 }, 3, 4), 3);
  assert.equal(effectiveAttachmentQuantity({ item_name: "风机", category_level1: "风机滤网", quantity: 2 }, 3, 4), 6);
  assert.equal(effectiveAttachmentQuantity({
    item_name: "固定底座",
    category_level1: "底座",
    quantity: 1,
    ganged_fixed_base_match: true,
    ganged_fixed_base_index: 0,
  }, 3, 4), 3);
});

test("manually selected ganged attachments already belong to the complete set", () => {
  assert.equal(effectiveAttachmentQuantity({
    item_name: "风机", quantity: 2, selection_source: "manual",
  }, 3), 6);
  assert.equal(effectiveAttachmentQuantity({
    item_name: "铜排", quantity: 2, selection_source: "manual",
  }, 3, 4), 6);
  assert.equal(effectiveAttachmentQuantity({
    item_name: "人工附件", quantity: 2, selection_source: "QUOTE_LOCAL",
  }, 3, 4), 6);
  assert.equal(effectiveAttachmentQuantity({
    item_name: "自动附件", quantity: 8, selection_source: "automatic",
  }, 3, 4), 24);
  assert.equal(effectiveAttachmentQuantity({
    item_name: "固定底座", quantity: 2, selection_source: "manual",
    ganged_fixed_base_match: true, ganged_fixed_base_index: 0,
  }, 3, 4), 6);
});

test("quick order line scales every attachment with the cabinet quantity", () => {
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
  // Discounted: cabinet 3000 - installation board 300 + side panels 300.
  // Original price: fan 90 + door transformation 450.
  assert.equal(result.eligibleAttachmentTotal, 0);
  assert.equal(result.originalPriceAttachmentTotal, 540);
  assert.equal(result.lineTotal, 3240);
  assert.equal(result.equivalentUnitTotal, 1080);
});

test("quick order line does not multiply attachments by the ganged split count", () => {
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
  assert.equal(result.eligibleAttachmentTotal, 0);
  assert.equal(result.originalPriceAttachmentTotal, 360);
  assert.equal(result.lineTotal, 3960);
  assert.equal(result.equivalentUnitTotal, 1980);
});

test("freight is not discounted and multiplies only the complete cabinet quantity", () => {
  const ordinary = quickOrderLineBreakdown({
    quote: { base_price: 1000, attachment_fee: 0, total_cost: 1000 },
    discount: 0.8,
    cabinetQuantity: 3,
    freightFee: 50,
  });
  assert.equal(ordinary.freightTotal, 150);
  assert.equal(ordinary.lineTotal, 2550);
  assert.equal(ordinary.equivalentUnitTotal, 850);

  const ganged = quickOrderLineBreakdown({
    quote: { base_price: 2000, attachment_fee: 0, total_cost: 2000 },
    discount: 0.8,
    cabinetQuantity: 3,
    gangedCabinetCount: 2,
    freightFee: 50,
  });
  assert.equal(ganged.freightTotal, 150);
  assert.equal(ganged.lineTotal, 4950);
});
