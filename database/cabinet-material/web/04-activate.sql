-- Prefer the unified activation script when deploying all catalogs together.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
SELECT calc.activate_cabinet_material_catalog_v2('cabinet-material-4f8bf726efa6568d-v2');
COMMIT;
