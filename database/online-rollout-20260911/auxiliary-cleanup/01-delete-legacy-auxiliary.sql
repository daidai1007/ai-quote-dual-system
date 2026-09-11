BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

DO $$
DECLARE v_version text;v_profiles integer;v_lines integer;v_fixed integer;
BEGIN
  SELECT data_version INTO v_version
  FROM calc.cabinet_auxiliary_catalog_version WHERE status='ACTIVE';
  IF v_version IS NULL OR v_version!~'-v2$' THEN
    RAISE EXCEPTION 'Complete auxiliary V2 catalog is not ACTIVE';
  END IF;
  SELECT count(*) INTO v_profiles FROM calc.cabinet_auxiliary_profile WHERE data_version=v_version;
  SELECT count(*) INTO v_lines FROM calc.cabinet_auxiliary_line l
    JOIN calc.cabinet_auxiliary_profile p USING(profile_id) WHERE p.data_version=v_version;
  SELECT count(*) INTO v_fixed FROM calc.cabinet_auxiliary_fixed_rule WHERE data_version=v_version;
  IF v_profiles<>16 OR v_lines<>255 OR v_fixed<>72 THEN
    RAISE EXCEPTION 'Active auxiliary V2 catalog is incomplete: profiles %, lines %, fixed %',v_profiles,v_lines,v_fixed;
  END IF;
  IF EXISTS(
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='calc' AND p.prokind IN ('f','p') AND (
      pg_get_functiondef(p.oid) ILIKE '%calc.auxiliary_bom%'
      OR pg_get_functiondef(p.oid) ILIKE '%calc.auxiliary_experience_price%')
  ) THEN
    RAISE EXCEPTION 'A calc function still references a legacy auxiliary table; run cabinet-auxiliary/web/01-create.sql first';
  END IF;
END $$;

DROP VIEW IF EXISTS calc.v_auxiliary_bom_cost;
DROP VIEW IF EXISTS calc.v_auxiliary_experience_price;
DROP TABLE IF EXISTS calc.auxiliary_bom_line;
DROP TABLE IF EXISTS calc.auxiliary_bom;
DROP TABLE IF EXISTS calc.auxiliary_experience_price;

-- The user selected “latest auxiliary catalog only”. Retired and superseded
-- staged versioned catalogs are deleted after the V2 completeness guard.
DELETE FROM calc.cabinet_auxiliary_catalog_version WHERE status<>'ACTIVE';

COMMIT;
