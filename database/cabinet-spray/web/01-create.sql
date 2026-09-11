-- Versioned cabinet spray-area rules from the approved spray workbook.
-- Additive: no catalog is activated and no legacy table is removed here.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE TABLE IF NOT EXISTS calc.cabinet_spray_catalog_version (
  data_version text PRIMARY KEY,
  source_file text NOT NULL,
  source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL CHECK(status IN ('STAGED','ACTIVE','RETIRED')),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  activated_at timestamptz,
  CHECK((status='ACTIVE')=(activated_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_spray_one_active
  ON calc.cabinet_spray_catalog_version((status)) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS calc.cabinet_spray_rule (
  rule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_spray_catalog_version(data_version) ON DELETE CASCADE,
  family text NOT NULL CHECK(family IN ('JS','JP','JA','JE','JK','JM')),
  body_thickness_profile_mm numeric,
  profile_label text NOT NULL,
  single_door_count integer NOT NULL CHECK(single_door_count BETWEEN 0 AND 2),
  double_door_count integer NOT NULL CHECK(double_door_count BETWEEN 0 AND 2),
  part_name text NOT NULL CHECK(btrim(part_name)<>''),
  area_formula text NOT NULL CHECK(btrim(area_formula)<>''),
  quantity_rule jsonb NOT NULL CHECK(jsonb_typeof(quantity_rule)='object'),
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK(source_row_no>0),
  source_column text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  UNIQUE(data_version,source_sheet,source_row_no,source_column),
  UNIQUE(data_version,family,body_thickness_profile_mm,single_door_count,double_door_count,part_name)
);
CREATE INDEX IF NOT EXISTS cabinet_spray_rule_lookup
  ON calc.cabinet_spray_rule(data_version,family,single_door_count,double_door_count,body_thickness_profile_mm);
COMMENT ON TABLE calc.cabinet_spray_rule IS
  'Cabinet spray area: safe area formula result multiplied by internal quantity. Waste factor never applies.';

DO $$ BEGIN
  IF to_regclass('calc.dual_quote_result') IS NOT NULL THEN
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_spray_version text;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_spray_snapshot jsonb;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_spray_catalog_v1(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_rule jsonb;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-spray-[0-9a-f]{16}-v[0-9]+$' THEN
    RAISE EXCEPTION 'Invalid cabinet spray data_version';
  END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'Invalid cabinet spray source SHA-256';
  END IF;
  IF jsonb_typeof(p_payload->'rules')<>'array' OR jsonb_array_length(p_payload->'rules')<>202 THEN
    RAISE EXCEPTION 'Expected exactly 202 cabinet spray rules';
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_spray_catalog_version WHERE data_version=v_version AND status='ACTIVE') THEN
    RAISE EXCEPTION 'Cannot overwrite ACTIVE cabinet spray version %',v_version;
  END IF;
  DELETE FROM calc.cabinet_spray_catalog_version WHERE data_version=v_version;
  INSERT INTO calc.cabinet_spray_catalog_version(data_version,source_file,source_sha256,status)
  VALUES(v_version,p_payload->>'source_file',p_payload->>'source_sha256','STAGED');
  FOR v_rule IN SELECT value FROM jsonb_array_elements(p_payload->'rules') LOOP
    INSERT INTO calc.cabinet_spray_rule(data_version,family,body_thickness_profile_mm,profile_label,
      single_door_count,double_door_count,part_name,area_formula,quantity_rule,
      source_sheet,source_row_no,source_column)
    VALUES(v_version,v_rule->>'family',NULLIF(v_rule->>'body_thickness_profile_mm','')::numeric,
      v_rule->>'profile_label',(v_rule->>'single_door_count')::integer,(v_rule->>'double_door_count')::integer,
      v_rule->>'part_name',v_rule->>'area_formula',v_rule->'quantity_rule',v_rule->>'source_sheet',
      (v_rule->>'source_row_no')::integer,v_rule->>'source_column');
  END LOOP;
  SELECT count(*) INTO v_count FROM calc.cabinet_spray_rule WHERE data_version=v_version;
  IF v_count<>202 OR (SELECT count(DISTINCT family) FROM calc.cabinet_spray_rule WHERE data_version=v_version)<>6 THEN
    RAISE EXCEPTION 'Staged cabinet spray catalog is incomplete';
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_spray_rule WHERE data_version=v_version
            AND (quantity_rule->>'kind') NOT IN ('CONSTANT','JS_DEPTH_HEIGHT')) THEN
    RAISE EXCEPTION 'Unsupported cabinet spray quantity rule';
  END IF;
  RETURN v_version;
END $$;
REVOKE ALL ON FUNCTION calc.stage_cabinet_spray_catalog_v1(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.activate_cabinet_spray_catalog_v1(p_version text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_count integer;v_family_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_spray_catalog_version'));
  SELECT count(*),count(DISTINCT family) INTO v_count,v_family_count
  FROM calc.cabinet_spray_rule WHERE data_version=p_version;
  IF NOT EXISTS(SELECT 1 FROM calc.cabinet_spray_catalog_version WHERE data_version=p_version AND status='STAGED')
     OR v_count<>202 OR v_family_count<>6 THEN
    RAISE EXCEPTION 'Version % is not a complete STAGED cabinet spray catalog',p_version;
  END IF;
  UPDATE calc.cabinet_spray_catalog_version SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_spray_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=p_version;
  RETURN p_version;
END $$;
REVOKE ALL ON FUNCTION calc.activate_cabinet_spray_catalog_v1(text) FROM PUBLIC;

COMMIT;
