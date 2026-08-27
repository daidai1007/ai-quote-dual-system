import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('Docker image includes every local module needed by the API and workbook exporter', async () => {
  const [serverSource, exporterSource, dockerfile, dockerignore] = await Promise.all([
    fs.readFile(path.join(projectRoot, 'api', 'server.mjs'), 'utf8'),
    fs.readFile(path.join(projectRoot, 'export_dual_quote_workbook.mjs'), 'utf8'),
    fs.readFile(path.join(projectRoot, 'Dockerfile'), 'utf8'),
    fs.readFile(path.join(projectRoot, '.dockerignore'), 'utf8'),
  ]);
  const apiModules = [
    ...serverSource.matchAll(/from '\.\/([^']+\.mjs)'/g),
  ].map((match) => `api/${match[1]}`);
  const exporterModules = [
    ...exporterSource.matchAll(/from "\.\/([^"]+\.mjs)"/g),
  ].map((match) => match[1]);
  const localModules = [
    'export_dual_quote_workbook.mjs',
    ...apiModules,
    ...exporterModules,
  ];

  assert.ok(localModules.length > 0);
  assert.doesNotMatch(serverSource, /quick_variant_code/, 'unused quick_variant_code transport field returned');
  assert.doesNotMatch(serverSource, /toISOString\(\)\.slice\(0, 10\)/, 'server date still depends on UTC');
  assert.match(serverSource, /timeZone: 'Asia\/Shanghai'/, 'server date does not use the business timezone');
  assert.match(serverSource, /\.trim\(\)\.toUpperCase\(\)/, 'product codes are not normalized at the API boundary');
  for (const modulePath of localModules) {
    assert.match(dockerfile, new RegExp(`\\b${modulePath.replaceAll('.', '\\.')}\\b`));
    assert.match(dockerignore, new RegExp(`^!${modulePath.replaceAll('.', '\\.')}\\s*$`, 'm'));
  }
});

const reservePort = () => new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once('error', reject);
  probe.listen(0, '127.0.0.1', () => {
    const address = probe.address();
    probe.close((error) => {
      if (error) reject(error);
      else resolve(address.port);
    });
  });
});

test('Docker-compatible server starts and serves a database-free health check', { timeout: 15000 }, async (t) => {
  const port = await reservePort();
  const child = spawn(process.execPath, ['api/server.mjs'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      RENDER: 'true',
      PORT: String(port),
      AI_QUOTE_API_KEY: 'cloud-test-key',
      DATABASE_URL: 'postgresql://test:test@example.neon.tech/quote_test?sslmode=require',
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => {
    if (!child.killed) child.kill();
  });

  let stderr = '';
  child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(stderr || 'server startup timed out')), 8000);
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.stdout.on('data', (chunk) => {
      if (chunk.toString().includes('AI quote dual API listening')) {
        clearTimeout(timer);
        resolve();
      }
    });
  });

  const response = await fetch(`http://127.0.0.1:${port}/health`);
  assert.equal(response.status, 200);
  const health = await response.json();
  assert.equal(health.ok, true);
  assert.equal(health.build, '2026-08-26-signed-attachments-v1');
  assert.equal(health.deployment, '20260826-signed-attachments-v4');
  assert.equal(health.database_checked, false);

  const protectedResponse = await fetch(`http://127.0.0.1:${port}/api/health/database`);
  assert.equal(protectedResponse.status, 401);

  const attachmentValidation = await fetch(`http://127.0.0.1:${port}/api/attachments/catalog`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
    body: JSON.stringify({ item_name: '', price: -1 }),
  });
  assert.equal(attachmentValidation.status, 400);

  const malformedJson = await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
    body: '{',
  });
  assert.equal(malformedJson.status, 400);

  const arrayPayload = await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
    body: '[]',
  });
  assert.equal(arrayPayload.status, 400);

  const validQuoteInput = {
    quote_id: 'TEST-ATTACHMENT-VALIDATION', product_code: 'js_single', material_code: 'SECC',
    width_mm: 1000, height_mm: 1800, depth_mm: 600,
  };
  for (const [field, attachment] of [
    ['quantity', { item_name: '附件', quantity: 0 }],
    ['width', { item_name: '附件', quantity: 1, width_mm: 0 }],
    ['override', { item_name: '附件', quantity: 1, unit_price_override: -1 }],
  ]) {
    const response = await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
      body: JSON.stringify({ ...validQuoteInput, quote_id: `${validQuoteInput.quote_id}-${field}`, attachments: [attachment] }),
    });
    assert.equal(response.status, 400, `invalid attachment ${field} returned ${response.status}`);
  }

  const arrayHistoryPayload = await fetch(`http://127.0.0.1:${port}/api/company-history`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
    body: JSON.stringify({
      company_code: 'TEST', product_code: 'js_single', material_code: 'SECC',
      width_mm: 1000, height_mm: 1800, depth_mm: 600, payload: [],
    }),
  });
  assert.equal(arrayHistoryPayload.status, 400);

  const doorValidation = await fetch(`http://127.0.0.1:${port}/api/quotes/calculate-dual`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ai-quote-key': 'cloud-test-key' },
    body: JSON.stringify({
      quote_id: 'TEST-INVALID-DOOR', product_code: 'JS_SINGLE', material_code: 'SECC',
      width_mm: 1000, height_mm: 1800, depth_mm: 600,
      single_door_count: 2, double_door_count: 1,
    }),
  });
  assert.equal(doorValidation.status, 400);
});
