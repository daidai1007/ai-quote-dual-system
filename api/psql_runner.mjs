import { spawn } from 'node:child_process';
import { buildPsqlArgs } from './runtime_config.mjs';

// These trigger messages contain no SQL, values, hostnames or credentials.
const safeAttachmentErrors = new Set([
  '附件归属或报价环境不一致', '附件目录版本或面价不一致', '该附件不允许扣减',
  '缺少附件身份/辅材清单快照', '附件身份或单位快照不一致',
  '所选成本规则不是当前产品适用规则', '成本规则仍有待确认事项',
  '成本规则版本或辅材清单不一致', '固定成本不一致',
  '缺少动态成本组成', '动态成本组成必须是非负数',
  '成本组成与单位成本不一致',
]);

const databaseError = (stderr, code, processError) => {
  // psql may close stdin as soon as ON_ERROR_STOP sees a SQL error.  Its
  // subsequent EPIPE must not hide the useful PostgreSQL error on stderr.
  const primary = String(stderr).split(/\r?\n/)
    .map(line => line.match(/(?:^|\s)(ERROR|FATAL):\s*(.+)/))
    .find(Boolean);
  if (primary) {
    const message = primary[2].trim();
    if (primary[1] === 'ERROR' && safeAttachmentErrors.has(message)) {
      return new Error(`PostgreSQL ERROR: ${message}`);
    }
    const constraint = message.match(/constraint\s+"([A-Za-z0-9_.-]+)"/i);
    if (primary[1].toUpperCase() === 'ERROR' && constraint) {
      return new Error(`PostgreSQL ERROR: constraint "${constraint[1]}" rejected the request`);
    }
    return new Error('psql failed; check database connection and server logs');
  }
  if (String(stderr).trim()) return new Error('psql failed; check database connection and server logs');
  if (processError) return processError;
  return new Error(`psql exited with code ${code}`);
};

export const runPsqlCommand = (sql, clientEncoding, config, spawnProcess = spawn) => new Promise((resolve, reject) => {
  const child = spawnProcess(config.psqlPath, buildPsqlArgs(config), {
    env: { ...process.env, PGCLIENTENCODING: clientEncoding },
    windowsHide: true,
  });
  let stdout = '';
  let stderr = '';
  let processError;
  let settled = false;
  const timeout = setTimeout(() => {
    if (settled) return;
    settled = true;
    if (!child.killed) child.kill();
    reject(new Error(`database command timed out after ${config.psqlTimeoutMs} ms`));
  }, config.psqlTimeoutMs);
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', chunk => { stdout += chunk; });
  child.stderr.on('data', chunk => { stderr += chunk; });
  // Node emits close after error and after stdio closes.  Wait for it so the
  // diagnostic line already written by psql is available before rejecting.
  child.on('error', error => { processError ||= error; });
  child.stdin.on('error', error => { processError ||= error; });
  child.on('close', code => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    if (code !== 0 || processError) reject(databaseError(stderr, code, processError));
    else resolve(stdout.trim());
  });
  // Send SQL through stdin: quotations can exceed the Windows command-line
  // length limit.  SQL and connection information are never logged here.
  child.stdin.end(`${sql}\n`, 'utf8');
});
