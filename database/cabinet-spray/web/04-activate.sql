-- Run only after matching Render API/client deployment and staged validation.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
SELECT calc.activate_cabinet_spray_catalog_v2('cabinet-spray-4b3d73c9cb7a6f26-v2');
COMMIT;
