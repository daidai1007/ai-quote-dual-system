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
