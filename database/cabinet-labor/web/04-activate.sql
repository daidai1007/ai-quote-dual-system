BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_labor_catalog_v1('cabinet-labor-a3d12580527a3eb6-v1');
COMMIT;
