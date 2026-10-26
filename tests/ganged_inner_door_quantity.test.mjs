import assert from 'node:assert/strict';
import test from 'node:test';
import {effectiveAttachmentQuantity, effectiveAttachmentLineAmount,
  effectiveFormulaAttachmentLineAmount} from '../quick_discount_rules.mjs';

const door = {item_name: '内门', quantity: 1, selection_source: 'manual',
  catalog_version: 'offline', ganged_inner_door_match: true,
  quick_amount: 448.31, formula_amount: 283};

test('separate inner doors multiply only by order quantity, not child count again', () => {
  assert.equal(effectiveAttachmentQuantity(door, 3, 2), 3);
  assert.equal(effectiveAttachmentLineAmount(door, 3, 2), 448.31 * 3);
  assert.equal(effectiveFormulaAttachmentLineAmount(door, 3, 2), 283 * 3);
  assert.equal(effectiveAttachmentQuantity({...door, quantity: 2, cost_quantity_manual: true}, 3, 2), 6);
});

test('whole-set manual rows multiply by order quantity once; explicit child rows remain separate', () => {
  assert.equal(effectiveAttachmentQuantity({quantity: 2, selection_source: 'manual',
    ganged_fixed_base_match: true}, 3, 4), 6);
  const manual={quantity:2,selection_source:'manual',quick_amount:20,formula_amount:14};
  assert.equal(effectiveAttachmentQuantity(manual,3,4),6);
  assert.equal(effectiveAttachmentLineAmount(manual,3,4),60);
  assert.equal(effectiveFormulaAttachmentLineAmount(manual,3,4),42);
  // Four independently expanded child rows really do contain 8 pieces/set.
  // Reapplying child count to each row would silently quadruple that amount.
  const children=Array.from({length:4},(_,ganged_cabinet_index)=>({...manual,ganged_cabinet_index}));
  assert.equal(children.reduce((sum,row)=>sum+effectiveAttachmentQuantity(row,3,4),0),24);
  assert.equal(children.reduce((sum,row)=>sum+effectiveAttachmentLineAmount(row,3,4),0),240);
});
