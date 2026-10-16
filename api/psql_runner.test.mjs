import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import { runPsqlCommand } from './psql_runner.mjs';

const config = { psqlPath: 'psql', psqlTimeoutMs: 1000, dbHost: 'localhost',
  dbPort: '5432', dbUser: 'test', dbName: 'test' };

function fakeSpawn(onInput) {
  return () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.stdout.setEncoding = () => {};
    child.stderr.setEncoding = () => {};
    child.stdin = new EventEmitter();
    child.stdin.end = input => onInput(child, input);
    child.kill = () => { child.killed = true; };
    return child;
  };
}

test('psql stderr wins over an earlier stdin EPIPE and does not expose SQL', async () => {
  const sql = 'INSERT INTO calc.attachment_selection VALUES (secret_payload)';
  const spawn = fakeSpawn((child, input) => {
    assert.equal(input, `${sql}\n`);
    child.stdin.emit('error', Object.assign(new Error('write EPIPE'), { code: 'EPIPE' }));
    child.stderr.emit('data', 'psql:<stdin>:3: ERROR:  new row violates check constraint "attachment_selection_v2_state"\n');
    child.stderr.emit('data', `LINE 3: ${sql}\n`);
    child.emit('close', 3);
  });
  await assert.rejects(runPsqlCommand(sql, 'UTF8', config, spawn), error => {
    assert.match(error.message, /PostgreSQL ERROR:.*attachment_selection_v2_state/);
    assert.doesNotMatch(error.message, /EPIPE|secret_payload|LINE 3/);
    return true;
  });
});

test('stdin EPIPE remains visible when psql provides no diagnostic', async () => {
  const spawn = fakeSpawn(child => {
    child.stdin.emit('error', Object.assign(new Error('write EPIPE'), { code: 'EPIPE' }));
    child.emit('close', 1);
  });
  await assert.rejects(runPsqlCommand('SELECT 1', 'UTF8', config, spawn), /write EPIPE/);
});

test('successful command still returns trimmed stdout', async () => {
  const spawn = fakeSpawn(child => {
    child.stdout.emit('data', '  {"ok":true}\n');
    child.emit('close', 0);
  });
  assert.equal(await runPsqlCommand('SELECT 1', 'UTF8', config, spawn), '{"ok":true}');
});

test('connection diagnostics do not reveal endpoint or credentials', async () => {
  const spawn = fakeSpawn(child => {
    child.stderr.emit('data', 'psql: error: connection to server at "secret.neon.tech" failed: password=secret\n');
    child.emit('close', 2);
  });
  await assert.rejects(runPsqlCommand('SELECT 1', 'UTF8', config, spawn), error => {
    assert.match(error.message, /check database connection/);
    assert.doesNotMatch(error.message, /secret.neon.tech|password=secret/);
    return true;
  });
});
