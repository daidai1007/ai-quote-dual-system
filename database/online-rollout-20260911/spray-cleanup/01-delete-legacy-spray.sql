BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

DO $$
DECLARE v_version text;v_area integer;v_fixed integer;
BEGIN
  SELECT data_version INTO v_version FROM calc.cabinet_spray_catalog_version WHERE status='ACTIVE';
  IF v_version<>'cabinet-spray-4b3d73c9cb7a6f26-v2' THEN
    RAISE EXCEPTION 'Complete spray V2 catalog is not ACTIVE';
  END IF;
  SELECT count(*) INTO v_area FROM calc.cabinet_spray_rule WHERE data_version=v_version;
  SELECT count(*) INTO v_fixed FROM calc.cabinet_spray_fixed_rule WHERE data_version=v_version;
  IF v_area<>202 OR v_fixed<>46 THEN
    RAISE EXCEPTION 'Active spray V2 catalog is incomplete: area %, fixed %',v_area,v_fixed;
  END IF;
  IF EXISTS(
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='calc' AND p.prokind IN ('f','p')
      AND pg_get_functiondef(p.oid) ILIKE '%calc.experience_spray_price%'
  ) THEN
    RAISE EXCEPTION 'A calc function still references calc.experience_spray_price; run cabinet-spray/web/01-create.sql first';
  END IF;
END $$;

DROP TABLE IF EXISTS calc.experience_spray_price;

-- Keep only the active complete spray catalog after business acceptance.
DELETE FROM calc.cabinet_spray_catalog_version WHERE status<>'ACTIVE';

COMMIT;
