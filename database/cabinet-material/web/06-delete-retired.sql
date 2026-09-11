-- Run only after 05-verify.sql and representative API quotes pass.
-- Deletes superseded area and fixed-weight rows from the replacement cabinet-material catalog only.
-- Historical quotes remain because they read cabinet_material_snapshot.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DELETE FROM calc.cabinet_material_catalog_version WHERE status='RETIRED';
COMMIT;
