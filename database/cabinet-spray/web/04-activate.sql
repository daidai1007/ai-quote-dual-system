-- Run only after matching Render API/client deployment and staged validation.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
SELECT calc.activate_cabinet_spray_catalog_v1('cabinet-spray-13f257f440859e3b-v1');
COMMIT;
