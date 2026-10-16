import {execFile, execFileSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';

const execute = promisify(execFile);
const root = fileURLToPath(new URL('../../', import.meta.url));
const executable = name => `${name}${process.platform === 'win32' ? '.exe' : ''}`;

const postgresBin = () => {
  const configured = process.env.LOCAL_TEST_POSTGRES_BIN
    || (process.env.ATTACHMENT_TEST_PSQL && path.dirname(process.env.ATTACHMENT_TEST_PSQL));
  if (configured) return path.resolve(configured);
  if (process.platform === 'win32' && existsSync('G:/PostgreSQL/18/bin/initdb.exe')) {
    return 'G:/PostgreSQL/18/bin';
  }
  const command = process.platform === 'win32' ? 'where.exe' : 'which';
  try {
    return path.dirname(execFileSync(command, [executable('initdb')], {
      encoding:'utf8', windowsHide:true,
    }).trim().split(/\r?\n/)[0]);
  } catch {
    throw new Error('Local PostgreSQL test binaries were not found; set LOCAL_TEST_POSTGRES_BIN to their bin directory.');
  }
};

const unusedLoopbackPort = async () => {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
};

/** Own a disposable loopback cluster; never use application database settings. */
export const startLocalPostgres = async () => {
  const bin = postgresBin();
  for (const name of ['initdb','pg_ctl','pg_controldata','psql']) {
    if (!existsSync(path.join(bin, executable(name)))) {
      throw new Error(`Missing local PostgreSQL test binary: ${name}`);
    }
  }
  const outputRoot = path.join(root, 'test-output');
  await fs.mkdir(outputRoot, {recursive:true});
  const directory = await fs.mkdtemp(path.join(outputRoot, 'local-postgres-'));
  const data = path.join(directory, 'data');
  const log = path.join(directory, 'postgres.log');
  const port = await unusedLoopbackPort();
  const user = 'quote_regression_test';
  const environment = {...process.env, LC_ALL:'C', PGCLIENTENCODING:'UTF8',
    PGCONNECT_TIMEOUT:'5', PGSSLMODE:'disable'};
  // Inherited application/service settings must not redirect a test connection
  // or apply production session options, credentials, or startup SQL.
  for (const key of ['DATABASE_URL','PGSERVICE','PGSERVICEFILE','PGPASSWORD',
    'PGPASSFILE','PGOPTIONS','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER']) {
    delete environment[key];
  }
  const options = {env:environment, encoding:'utf8', windowsHide:true,
    timeout:45000, maxBuffer:8 * 1024 * 1024};
  let started = false;
  let closed = false;
  const query = (sql, database = 'postgres') => execFileSync(path.join(bin, executable('psql')),
    ['-X','-w','-h','127.0.0.1','-p',String(port),'-U',user,
      '-v','ON_ERROR_STOP=1','-A','-t','-q','-d',database], {...options,input:sql}).trim();
  const close = async () => {
    if (closed) return;
    if (started || existsSync(path.join(data, 'postmaster.pid'))) {
      await execute(path.join(bin, executable('pg_ctl')), ['-D',data,'-m','fast','-w','-t','20','stop'], options);
    }
    // Delete only the exact fresh test directory after its server has stopped.
    const resolved = path.resolve(directory);
    if (path.dirname(resolved) !== path.resolve(outputRoot)
      || !path.basename(resolved).startsWith('local-postgres-')) {
      throw new Error('Unexpected local PostgreSQL cleanup directory');
    }
    await fs.rm(resolved, {recursive:true,force:true});
    closed = true;
  };
  try {
    await execute(path.join(bin, executable('initdb')),
      ['-D',data,'-U',user,'-A','trust','--encoding=UTF8','--locale=C'], options);
    await execute(path.join(bin, executable('pg_ctl')),
      ['-D',data,'-l',log,'-o',`-h 127.0.0.1 -p ${port} -F`,'-w','-t','20','start'], options);
    started = true;
    // A port can be taken between reservation and startup. Verify our cluster
    // identity with read-only queries before allowing any test writes.
    const control = await execute(path.join(bin, executable('pg_controldata')), ['-D',data], options);
    const identifier = control.stdout.match(/Database system identifier:\s*(\d+)/)?.[1];
    if (!identifier || query('SELECT system_identifier FROM pg_control_system();') !== identifier) {
      throw new Error('Local test PostgreSQL cluster identity did not match');
    }
    return {query,close};
  } catch (error) {
    await close();
    throw error;
  }
};
