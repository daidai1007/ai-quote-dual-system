import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import {withQuoteRequest, withQuoteChild, timedQuotePhase, emitQuoteProgress, startQuoteStream, sqlTimingFields} from '../api/quote_telemetry.mjs';
import {calculateGangedBatch, validateGangedBatch} from '../api/ganged_quote_service.mjs';

test('real streamed events precede final result, correlate request and retain parallel child timing', async () => {
  const logs = [], originalLog = console.info;
  console.info = line => logs.push(JSON.parse(line));
  const server = http.createServer((req, res) => withQuoteRequest(req, res, async () => {
    const stream = startQuoteStream(req, res);
    const input = validateGangedBatch({cabinets: [{quote_id:'1'}, {quote_id:'2'}]}, child => child);
    const result = await calculateGangedBatch(input, {
      onProgress: emitQuoteProgress,
      calculateChild: child => withQuoteChild(Number(child.quote_id), () => timedQuotePhase('child_calculation', async () => {
        await new Promise(resolve => setTimeout(resolve, child.quote_id === '1' ? 30 : 5));
        return {formula_cost:{total_cost:10}, quick_quote:{base_price:20}};
      })),
    });
    stream.result(result);
  }));
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/quotes/calculate-ganged`, {
      headers:{accept:'application/x-ndjson','x-quote-request-id':'trace-test','x-ai-quote-key':'SECRET'},
    });
    assert.equal(response.headers.get('x-quote-request-id'), 'trace-test');
    assert.match(response.headers.get('content-type'), /ndjson/);
    const events = (await response.text()).trim().split('\n').map(JSON.parse);
    assert.deepEqual(events.filter(event => event.type === 'progress').map(event => event.completed), [0, 1, 2]);
    assert.equal(events[1].child_index, 2);
    assert.equal(events.at(-1).type, 'result');
    assert.equal(events.at(-1).result.ganged_batch_contract, 1);
    assert.ok(events.every(event => event.request_id === 'trace-test'));
    assert.ok(logs.some(event => event.phase === 'child_calculation' && event.child_index === 1 && event.elapsed_ms >= 25));
    assert.ok(logs.some(event => event.phase === 'child_calculation' && event.child_index === 2 && event.status === 'ok'));
    assert.doesNotMatch(JSON.stringify(logs), /SECRET/);
  } finally {
    await new Promise(resolve => server.close(resolve));
    console.info = originalLog;
  }
});

test('SQL timing metadata excludes literals and personal data', () => {
  assert.deepEqual(sqlTimingFields("UPDATE calc.dual_quote_result SET secret='COMPANY AND PASSWORD'"), {
    operation:'UPDATE', query_kind:'dual_quote_result',
  });
});
