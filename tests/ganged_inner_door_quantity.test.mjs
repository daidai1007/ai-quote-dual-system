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

test('fixed bases and ordinary manual attachments retain their quantity rules', () => {
  assert.equal(effectiveAttachmentQuantity({quantity: 2, selection_source: 'manual',
    ganged_fixed_base_match: true}, 3, 4), 6);
  assert.equal(effectiveAttachmentQuantity({quantity: 2, selection_source: 'manual'}, 3, 4), 24);
});
