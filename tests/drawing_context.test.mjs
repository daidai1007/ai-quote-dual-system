import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeDrawingContext } from '../api/drawing_context.mjs';

test('drawing context preserves the currently recognized page', () => {
  assert.deepEqual(normalizeDrawingContext({
    source_name: 'JP柜体.pdf', page_number: 2, page_count: 4,
  }), { source_name: 'JP柜体.pdf', page_number: 2, page_count: 4 });
});

test('drawing context rejects invalid or cross-page values', () => {
  assert.throws(() => normalizeDrawingContext({source_name:'a.pdf',page_number:3,page_count:2}), /valid positive integers/);
  assert.throws(() => normalizeDrawingContext({source_name:'',page_number:1,page_count:1}), /source_name/);
  assert.equal(normalizeDrawingContext(null), null);
});
