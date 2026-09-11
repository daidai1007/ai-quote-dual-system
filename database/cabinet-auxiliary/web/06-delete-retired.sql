BEGIN;
SET LOCAL lock_timeout='5s';
DELETE FROM calc.cabinet_auxiliary_catalog_version WHERE status='RETIRED';
COMMIT;
