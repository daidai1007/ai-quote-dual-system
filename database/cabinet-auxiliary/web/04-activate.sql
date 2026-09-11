BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_auxiliary_catalog_v2('cabinet-auxiliary-706c234a5de12a39-v2');
COMMIT;
