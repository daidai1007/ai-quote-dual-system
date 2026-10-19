import assert from 'node:assert/strict';
import test from 'node:test';
import {calculateAttachment} from '../api/attachment_cost.mjs';
import {PRICING_BASIS, moneyProduct} from '../quick_discount_rules.mjs';

const environment={product_code:'JP',width_mm:800,height_mm:2000,depth_mm:600,
  material_code:'SECC',pricing_basis:PRICING_BASIS};
const version='precision-catalog';

test('screenshot base and side panel keep exact catalogue prices apart from two-decimal popup prices',()=>{
  for(const item of [
    {item_name:'固定底座',width_mm:800,height_mm:100,depth_mm:600,price:264.6081},
    {item_name:'JP控制柜侧板',width_mm:null,height_mm:2000,depth_mm:600,price:737.216821},
  ]) for(const quantity of [1,10]) {
    const row=calculateAttachment({quantity,manual_inputs:{底座高度:100}},
      {...item,data_version:version},[],environment);
    assert.equal(row.status,'QUICK_ONLY');
    assert.equal(row.catalog_version,version);
    assert.equal(row.catalogue_face_price,item.price);
    assert.equal(row.catalogue_quick_amount,Number((item.price*quantity).toFixed(2)));
    assert.equal(row.quick_amount,moneyProduct(row.matched_price,quantity));
    assert.notEqual(row.matched_price,row.catalogue_face_price);
  }
});

test('non-sized attachments retain raw prices and audit extensions too, without changing unit-first rounding',()=>{
  const row=calculateAttachment({quantity:10},{item_name:'风机',price:1.005,data_version:version},[],environment);
  assert.equal(row.catalogue_face_price,1.005);
  assert.equal(row.catalogue_quick_amount,10.05);
  assert.equal(row.face_price,1.01);
  assert.equal(row.quick_amount,10.1);
});

test('perimeter price, deduction and missing dimensions never replace raw catalogue provenance',()=>{
  const item={item_name:'安装板',price:483.46155,width_mm:800,height_mm:2000,
    depth_mm:null,data_version:version};
  const selected={quantity:3,attachment_price_sign:-1};
  const row=calculateAttachment(selected,item,[],{...environment,width_mm:700,height_mm:1800});
  assert.equal(row.catalogue_face_price,483.46155);
  assert.equal(row.catalogue_quick_amount,-1450.38);
  assert.notEqual(row.quick_amount,row.catalogue_quick_amount);
  assert.equal(row.quick_amount,moneyProduct(row.unit_price_override,3,-1));
  const missing=calculateAttachment({quantity:1},item,[{
    rule_id:1,method:'CALCULATED',formulas:{weight_kg:'底座高度'},
  }],environment);
  assert.equal(missing.status,'ERROR');
  assert.equal(missing.catalogue_face_price,item.price);
  assert.equal(missing.catalogue_quick_amount,483.46);
});

test('client supplied prices cannot tamper with catalogue audit fields',()=>{
  const row=calculateAttachment({quantity:2,catalogue_face_price:0,catalogue_quick_amount:0,
    face_price:0,quick_amount:0,unit_price_override:0},
  {item_name:'风机',price:51.234567,data_version:version},[],environment);
  assert.equal(row.catalogue_face_price,51.234567);
  assert.equal(row.catalogue_quick_amount,102.47);
  assert.equal(row.quick_amount,102.46);
});

test('legacy calculations preserve previous effective price and amount semantics',()=>{
  const row=calculateAttachment({quantity:10},{item_name:'风机',price:1.005,data_version:version},[],{});
  assert.equal(row.face_price,1.005);
  assert.equal(row.matched_price,1.005);
  assert.equal(row.quick_amount,10.05);
  assert.equal(row.catalogue_face_price,1.005);
  assert.equal(row.catalogue_quick_amount,10.05);
});
