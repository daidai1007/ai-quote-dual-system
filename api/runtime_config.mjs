const envValue = (env, ...names) => {
  for (const name of names) {
    const value = String(env[name] ?? '').trim();
    if (value) return value;
  }
  return '';
};

const integerSetting = (value, name, fallback, minimum, maximum) => {
  const text = String(value ?? '').trim();
  if (!text) return fallback;
  const parsed = Number(text);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
};

const isLoopbackHost = (host) => ['127.0.0.1', '::1', 'localhost'].includes(
  String(host || '').toLowerCase(),
);

const validateDatabaseUrl = (value) => {
  if (!value) return '';
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('DATABASE_URL must be a valid PostgreSQL connection URL');
  }
  if (!['postgres:', 'postgresql:'].includes(parsed.protocol)) {
    throw new Error('DATABASE_URL must use the postgres or postgresql protocol');
  }
  return value;
};

const resolveRuntimeConfig = (env = process.env) => {
  const renderRuntime = Boolean(envValue(env, 'RENDER'));
  const port = integerSetting(
    envValue(env, 'PORT', 'AI_QUOTE_API_PORT', 'AI_QUOTE_PORT'),
    'PORT',
    8080,
    1,
    65535,
  );
  const host = envValue(env, 'AI_QUOTE_API_HOST', 'AI_QUOTE_HOST')
    || (renderRuntime ? '0.0.0.0' : '127.0.0.1');
  const apiKey = envValue(env, 'AI_QUOTE_API_KEY');
  if (!isLoopbackHost(host) && !apiKey) {
    throw new Error('AI_QUOTE_API_KEY is required when the API is exposed beyond this computer');
  }

  return Object.freeze({
    host,
    port,
    apiKey,
    psqlPath: envValue(env, 'PSQL_PATH') || 'psql',
    psqlTimeoutMs: integerSetting(
      envValue(env, 'AI_QUOTE_PSQL_TIMEOUT_MS'),
      'AI_QUOTE_PSQL_TIMEOUT_MS',
      30000,
      1000,
      300000,
    ),
    databaseUrl: validateDatabaseUrl(envValue(env, 'DATABASE_URL')),
    dbHost: envValue(env, 'AI_QUOTE_DB_HOST') || '127.0.0.1',
    dbPort: envValue(env, 'AI_QUOTE_DB_PORT') || '5432',
    dbName: envValue(env, 'AI_QUOTE_DB_NAME') || 'ai_quote_dev',
    dbUser: envValue(env, 'AI_QUOTE_DB_USER') || 'postgres',
  });
};

const buildPsqlArgs = (config, { singleTransaction = false } = {}) => [
  '-X', '-w', '-A', '-t', '-q',
  ...(singleTransaction ? ['-1'] : []),
  '-v', 'ON_ERROR_STOP=1',
  ...(config.databaseUrl
    ? ['-d', config.databaseUrl]
    : [
      '-h', config.dbHost,
      '-p', config.dbPort,
      '-U', config.dbUser,
      '-d', config.dbName,
    ]),
];

export {
  buildPsqlArgs,
  isLoopbackHost,
  resolveRuntimeConfig,
};
