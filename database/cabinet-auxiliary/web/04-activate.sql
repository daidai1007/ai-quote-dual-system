BEGIN;
SET LOCAL lock_timeout='5s';
SELECT calc.activate_cabinet_auxiliary_catalog_v1('cabinet-auxiliary-1dc400290ae91924-v1');
COMMIT;
