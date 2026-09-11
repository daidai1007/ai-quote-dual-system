-- Versioned cabinet labor rules. Formula quotation only; quick quotation is untouched.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE TABLE IF NOT EXISTS calc.cabinet_labor_catalog_version (
  data_version text PRIMARY KEY,
  source_file text NOT NULL,
  source_sha256 text NOT NULL CHECK (source_sha256~'^[0-9a-f]{64}$'),
  status text NOT NULL CHECK (status IN ('STAGED','ACTIVE','RETIRED')),
  management_fee_rate numeric NOT NULL CHECK (management_fee_rate>=0 AND management_fee_rate<=1),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  activated_at timestamptz,
  CHECK ((status='ACTIVE')=(activated_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_labor_one_active
  ON calc.cabinet_labor_catalog_version((status)) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS calc.cabinet_labor_rule (
  rule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_labor_catalog_version(data_version) ON DELETE CASCADE,
  rule_kind text NOT NULL CHECK (rule_kind IN ('LINEAR_WEIGHT','FIXED')),
  product_code text NOT NULL,
  profile_code text,
  material_codes jsonb NOT NULL CHECK (jsonb_typeof(material_codes)='array' AND jsonb_array_length(material_codes)>0),
  model_code text,
  width_mm numeric,
  height_mm numeric,
  depth_mm numeric,
  intercept numeric,
  slope numeric,
  excluded_part_names jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(excluded_part_names)='array'),
  labor_cost numeric,
  allow_dimension_scale boolean NOT NULL DEFAULT false,
  source_formula text,
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK (source_row_no>0),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  CHECK ((rule_kind='LINEAR_WEIGHT' AND intercept IS NOT NULL AND slope IS NOT NULL AND labor_cost IS NULL)
      OR (rule_kind='FIXED' AND labor_cost IS NOT NULL AND width_mm>0 AND height_mm>0 AND depth_mm>0)),
  UNIQUE(data_version,source_sheet,source_row_no)
);
CREATE INDEX IF NOT EXISTS cabinet_labor_rule_lookup
  ON calc.cabinet_labor_rule(data_version,product_code,rule_kind,profile_code,model_code);

DO $$ BEGIN
  IF to_regclass('calc.dual_quote_result') IS NOT NULL THEN
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_labor_version text;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_labor_snapshot jsonb;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_labor_catalog_v1(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_rule jsonb;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-labor-[0-9a-f]{16}-v[0-9]+$' THEN RAISE EXCEPTION 'Invalid cabinet labor data_version'; END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid source SHA-256'; END IF;
  IF jsonb_typeof(p_payload->'rules')<>'array' OR jsonb_array_length(p_payload->'rules')<>57 THEN RAISE EXCEPTION 'Expected exactly 57 labor rules'; END IF;
  IF (p_payload->>'management_fee_rate')::numeric<>0.13 THEN RAISE EXCEPTION 'Expected management fee rate 0.13'; END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_labor_catalog_version WHERE data_version=v_version AND status='ACTIVE') THEN RAISE EXCEPTION 'Cannot overwrite ACTIVE labor version %',v_version; END IF;
  DELETE FROM calc.cabinet_labor_catalog_version WHERE data_version=v_version;
  INSERT INTO calc.cabinet_labor_catalog_version(data_version,source_file,source_sha256,status,management_fee_rate)
  VALUES(v_version,p_payload->>'source_file',p_payload->>'source_sha256','STAGED',(p_payload->>'management_fee_rate')::numeric);
  FOR v_rule IN SELECT value FROM jsonb_array_elements(p_payload->'rules') LOOP
    INSERT INTO calc.cabinet_labor_rule(data_version,rule_kind,product_code,profile_code,material_codes,model_code,
      width_mm,height_mm,depth_mm,intercept,slope,excluded_part_names,labor_cost,allow_dimension_scale,
      source_formula,source_sheet,source_row_no)
    VALUES(v_version,v_rule->>'rule_kind',v_rule->>'product_code',NULLIF(v_rule->>'profile_code',''),v_rule->'material_codes',
      NULLIF(v_rule->>'model_code',''),NULLIF(v_rule->>'width_mm','')::numeric,NULLIF(v_rule->>'height_mm','')::numeric,
      NULLIF(v_rule->>'depth_mm','')::numeric,NULLIF(v_rule->>'intercept','')::numeric,NULLIF(v_rule->>'slope','')::numeric,
      coalesce(v_rule->'excluded_part_names','[]'::jsonb),NULLIF(v_rule->>'labor_cost','')::numeric,
      coalesce((v_rule->>'allow_dimension_scale')::boolean,false),NULLIF(v_rule->>'source_formula',''),
      v_rule->>'source_sheet',(v_rule->>'source_row_no')::integer);
  END LOOP;
  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule WHERE data_version=v_version;
  IF v_count<>57 THEN RAISE EXCEPTION 'Staged labor count %, expected 57',v_count; END IF;
  RETURN v_version;
END $$;
REVOKE ALL ON FUNCTION calc.stage_cabinet_labor_catalog_v1(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.activate_cabinet_labor_catalog_v1(p_version text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_labor_catalog_version'));
  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule WHERE data_version=p_version;
  IF NOT EXISTS(SELECT 1 FROM calc.cabinet_labor_catalog_version WHERE data_version=p_version AND status='STAGED') OR v_count<>57
    THEN RAISE EXCEPTION 'Version % is not a complete STAGED labor catalog',p_version; END IF;
  UPDATE calc.cabinet_labor_catalog_version SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_labor_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=p_version;
  RETURN p_version;
END $$;
REVOKE ALL ON FUNCTION calc.activate_cabinet_labor_catalog_v1(text) FROM PUBLIC;
COMMIT;
