-- Run only after the matching API/client build has been deployed and validated.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
SELECT calc.activate_cabinet_material_catalog_v1('cabinet-material-91cc0a5f841b7455-v1');
COMMIT;
