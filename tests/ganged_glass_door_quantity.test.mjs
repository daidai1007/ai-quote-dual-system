import assert from 'node:assert/strict';
import test from 'node:test';
import {effectiveAttachmentQuantity, effectiveAttachmentLineAmount,
  effectiveFormulaAttachmentLineAmount} from '../quick_discount_rules.mjs';

test('per-child glass doors do not multiply by child count twice', () => {
  const door = {item_name: '玻璃门', quantity: 1, selection_source: 'manual',
    catalog_version: 'offline', ganged_glass_door_match: true,
    quick_amount: 500, formula_amount: 300};
  assert.equal(effectiveAttachmentQuantity(door, 3, 2), 3);
  assert.equal(effectiveAttachmentLineAmount(door, 3, 2), 1500);
  assert.equal(effectiveFormulaAttachmentLineAmount(door, 3, 2), 900);
  assert.equal(effectiveAttachmentQuantity({...door, quantity: 2, cost_quantity_manual: true}, 3, 2), 6);
});
