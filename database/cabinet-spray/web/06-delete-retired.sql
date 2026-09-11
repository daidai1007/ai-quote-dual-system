-- Run only after representative quotes, save/reopen, and export pass.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DELETE FROM calc.cabinet_spray_catalog_version WHERE status='RETIRED';
COMMIT;
