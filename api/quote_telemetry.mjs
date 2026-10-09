import {AsyncLocalStorage} from 'node:async_hooks';
import {randomUUID} from 'node:crypto';
import {performance} from 'node:perf_hooks';

const requests = new AsyncLocalStorage();
const safeFields = new Set(['phase', 'elapsed_ms', 'status', 'child_index', 'completed', 'total', 'query_kind', 'operation', 'cache_hit']);
export function recordQuoteEvent(event, fields = {}) {
  const context = requests.getStore();
  if (!context || context.quiet) return;
  // Never log SQL, request bodies, prices, company details, API keys or DB URLs.
  console.info(JSON.stringify({event, request_id: context.request_id, endpoint: context.endpoint,
    ...(context.child_index == null ? {} : {child_index: context.child_index}),
    ...Object.fromEntries(Object.entries(fields).filter(([key]) => safeFields.has(key)))}));
}

export function withQuoteRequest(req, res, action) {
  const provided = String(req.headers['x-quote-request-id'] || '');
  const request_id = /^[a-zA-Z0-9_-]{1,64}$/.test(provided) ? provided : randomUUID();
  const context = {request_id, endpoint: String(req.url || '').split('?')[0],
    quiet: req.url === '/health', progress: null};
  res.setHeader('X-Quote-Request-Id', request_id);
  return requests.run(context, () => {
    const started = performance.now();
    recordQuoteEvent('request_started');
    res.once('finish', () => requests.run(context, () => recordQuoteEvent('request_finished', {
      elapsed_ms: Math.round(performance.now() - started), status: res.statusCode,
    })));
    return action();
  });
}

export function withQuoteChild(child_index, action) {
  return requests.run({...requests.getStore(), child_index}, action);
}

export async function timedQuotePhase(phase, action, fields = {}) {
  const started = performance.now();
  recordQuoteEvent('phase_started', {phase, ...fields});
  try {
    const result = await action();
    recordQuoteEvent('phase_finished', {phase, ...fields, status: 'ok', elapsed_ms: Math.round(performance.now() - started)});
    return result;
  } catch (error) {
    recordQuoteEvent('phase_finished', {phase, ...fields, status: 'failed', elapsed_ms: Math.round(performance.now() - started)});
    throw error;
  }
}

export function emitQuoteProgress(stage, fields = {}) {
  const context = requests.getStore();
  recordQuoteEvent('progress', {phase: stage, ...fields});
  // Parallel children are logged independently. Parent progress, not child
  // writes, advances the operator's batch progress through attachment/save.
  if (context?.child_index != null) return;
  context?.progress?.({type: 'progress', request_id: context.request_id, stage, ...fields});
}

export function startQuoteStream(req, res) {
  if (!String(req.headers.accept || '').includes('application/x-ndjson')) return null;
  const context = requests.getStore();
  res.writeHead(200, {'Content-Type': 'application/x-ndjson; charset=utf-8',
    'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'});
  res.flushHeaders();
  const send = value => {if (!res.destroyed && !res.writableEnded) res.write(`${JSON.stringify(value)}\n`);};
  context.progress = send;
  return {
    result: value => {send({type: 'result', request_id: context.request_id, result: value}); res.end();},
    error: error => {recordQuoteEvent('calculation_failed', {status: 'failed'}); send({type: 'error', request_id: context.request_id,
      error: 'quote_calculation_failed', message: String(error.message || '计算失败')}); res.end();},
  };
}

export function sqlTimingFields(sql) {
  return {operation: String(sql).match(/\b(SELECT|UPDATE|INSERT|DELETE|BEGIN)\b/i)?.[1].toUpperCase() || 'OTHER',
    query_kind: [...new Set([...String(sql).matchAll(/\bcalc\.([a-z_][a-z0-9_]*)/gi)].map(match => match[1]))].slice(0, 4).join(',')};
}
