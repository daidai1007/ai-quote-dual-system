// Package the reviewed SQL for a web editor: no psql client commands.
import fs from 'node:fs/promises';
import path from 'node:path';
const base='database/attachment-v2';
const output=path.join(base,'web');
await fs.mkdir(output,{recursive:true});
const read=relative=>fs.readFile(relative,'utf8');
const web=text=>text.replace(/^\\set[^\r\n]*(?:\r?\n|$)/gm,'');
const body=text=>web(text).replace(/^(?:BEGIN;|COMMIT;)\r?\n/gm,'');
const preparationFiles=['database/migrations/attachment_cost_v2.sql',`${base}/02-import-functions.sql`,`${base}/02b-snapshot-guards.sql`];
const preparation=[];
for(const file of preparationFiles) preparation.push(`-- Source: ${file}\n${body(await read(file))}`);
await fs.writeFile(path.join(output,'01-prepare.sql'),`-- Web editor: execute the WHOLE file. On any error ROLLBACK; do not continue to import.\n-- Installs the reviewed schema/functions in one transaction; no catalog import or switch.\nBEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='120s';\n${preparation.join('\n')}\nSELECT 'READY: schema prepared; current catalog and quotation history retained' AS result;\nCOMMIT;\n`);
await fs.writeFile(path.join(output,'02-stage.sql'),web(await read(`${base}/generated/03-stage-only.sql`)));
await fs.writeFile(path.join(output,'03-verify.sql'),web(await read(`${base}/04a-stage-acceptance.sql`))+`\n-- Summary of current database counts; existing history may grow during normal quoting.\nSELECT
  v.data_version,v.status,
  (SELECT count(*) FROM calc.attachment_price) AS catalog_total,
  (SELECT count(*) FROM calc.attachment_price WHERE is_active) AS active_total,
  (SELECT count(*) FROM calc.attachment_classification) AS classification_total,
  (SELECT count(*) FROM calc.attachment_selection) AS selection_total,
  (SELECT count(*) FROM calc.attachment_price WHERE data_version=v.data_version) AS new_catalog_rows,
  (SELECT count(*) FROM calc.attachment_price WHERE data_version=v.data_version AND is_active) AS new_active_rows,
  (SELECT count(*) FROM calc.attachment_cost_rule WHERE data_version=v.data_version) AS rules
FROM calc.attachment_catalog_version v WHERE status='STAGED' ORDER BY v.created_at;\n`);
console.log('Generated web/01-prepare.sql, web/02-stage.sql and web/03-verify.sql');
