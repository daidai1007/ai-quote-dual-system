import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPsqlArgs, resolveRuntimeConfig } from './runtime_config.mjs';

test('local defaults remain compatible with the Windows development API', () => {
  const config = resolveRuntimeConfig({});
  assert.equal(config.host, '127.0.0.1');
  assert.equal(config.port, 8080);
  assert.equal(config.dbName, 'ai_quote_dev');
  assert.deepEqual(buildPsqlArgs(config).slice(-8), [
    '-h', '127.0.0.1', '-p', '5432', '-U', 'postgres', '-d', 'ai_quote_dev',
  ]);
});

test('Render uses PORT and a single Neon DATABASE_URL without exposing its parts', () => {
  const databaseUrl = 'postgresql://quote_user:secret@example.neon.tech/quote_test?sslmode=require';
  const config = resolveRuntimeConfig({
    RENDER: 'true',
    PORT: '10000',
    AI_QUOTE_API_KEY: 'test-key',
    DATABASE_URL: databaseUrl,
  });
  assert.equal(config.host, '0.0.0.0');
  assert.equal(config.port, 10000);
  assert.deepEqual(buildPsqlArgs(config).slice(-2), ['-d', databaseUrl]);
  assert.equal(buildPsqlArgs(config).includes('-h'), false);
});

test('a publicly bound API refuses to start without an access key', () => {
  assert.throws(
    () => resolveRuntimeConfig({ RENDER: 'true', PORT: '10000' }),
    /AI_QUOTE_API_KEY is required/,
  );
});

test('invalid cloud settings fail before the server starts', () => {
  assert.throws(
    () => resolveRuntimeConfig({ PORT: 'not-a-number' }),
    /PORT must be an integer/,
  );
  assert.throws(
    () => resolveRuntimeConfig({ DATABASE_URL: 'https://example.com/database' }),
    /postgres or postgresql/,
  );
});
