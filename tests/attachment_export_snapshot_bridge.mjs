// Offline bridge: exercise the production snapshot guard without a database.
import { readFileSync } from 'node:fs';
import { createAttachmentService } from '../api/attachment_service.mjs';

const { payload, snapshots } = JSON.parse(readFileSync(0, 'utf8'));
const service = createAttachmentService({
  runPsql: async sql => {
    const match = sql.match(/decode\('([0-9a-f]+)','hex'\)/);
    const lineId = match && Buffer.from(match[1], 'hex').toString('utf8');
    if (!lineId || !Object.hasOwn(snapshots, lineId)) throw new Error('Unexpected offline SQL');
    return JSON.stringify(snapshots[lineId]);
  },
  calculateBase: async () => { throw new Error('Unexpected recalculation'); },
});
process.stdout.write(JSON.stringify(await service.hydrateDocument(payload)));
