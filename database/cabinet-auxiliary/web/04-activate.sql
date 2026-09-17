BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_auxiliary_catalog_v3('cabinet-auxiliary-189ae4efbfcb40f5-v3');
COMMIT;
