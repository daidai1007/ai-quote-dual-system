BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_auxiliary_catalog_v3('cabinet-auxiliary-fef2b7a93d50e60c-v3');
COMMIT;
