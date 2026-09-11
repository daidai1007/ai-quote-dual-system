-- Versioned cabinet auxiliary BOM. Formula quotation only; quick quotation is untouched.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE TABLE IF NOT EXISTS calc.cabinet_auxiliary_catalog_version (
  data_version text PRIMARY KEY,
  source_file text NOT NULL,
  source_sha256 text NOT NULL CHECK(source_sha256~'^[0-9a-f]{64}$'),
  status text NOT NULL CHECK(status IN ('STAGED','ACTIVE','RETIRED')),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  activated_at timestamptz,
  CHECK((status='ACTIVE')=(activated_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_auxiliary_one_active
  ON calc.cabinet_auxiliary_catalog_version((status)) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS calc.cabinet_auxiliary_profile (
  profile_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_auxiliary_catalog_version(data_version) ON DELETE CASCADE,
  profile_key text NOT NULL,
  product_code text NOT NULL CHECK(product_code IN ('JA','JE','JS','JP','JM')),
  single_door_count integer NOT NULL CHECK(single_door_count BETWEEN 0 AND 2),
  double_door_count integer NOT NULL CHECK(double_door_count BETWEEN 0 AND 2),
  source_sheet text NOT NULL,
  source_summary_formula text NOT NULL,
  source_cached_total numeric,
  UNIQUE(data_version,profile_key),UNIQUE(data_version,source_sheet)
);
CREATE INDEX IF NOT EXISTS cabinet_auxiliary_profile_lookup
  ON calc.cabinet_auxiliary_profile(data_version,product_code,single_door_count,double_door_count);

CREATE TABLE IF NOT EXISTS calc.cabinet_auxiliary_line (
  line_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  profile_id bigint NOT NULL REFERENCES calc.cabinet_auxiliary_profile(profile_id) ON DELETE CASCADE,
  line_no integer NOT NULL,
  item_code text,
  item_name text NOT NULL CHECK(btrim(item_name)<>''),
  spec_model text,
  material_name text,
  quantity_rule jsonb NOT NULL CHECK(jsonb_typeof(quantity_rule)='object'),
  unit_price numeric NOT NULL CHECK(unit_price>=0),
  cost_kind text NOT NULL CHECK(cost_kind IN ('UNIT','LENGTH','LENGTH_WITH_SPRAY')),
  length_formula text,
  spray_width_m numeric,
  notes text,
  source_total_formula text NOT NULL,
  source_cached_total numeric,
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK(source_row_no>0),
  CHECK((cost_kind='UNIT' AND length_formula IS NULL AND spray_width_m IS NULL)
     OR (cost_kind='LENGTH' AND length_formula IS NOT NULL AND spray_width_m IS NULL)
     OR (cost_kind='LENGTH_WITH_SPRAY' AND length_formula IS NOT NULL AND spray_width_m>0)),
  UNIQUE(profile_id,line_no),UNIQUE(profile_id,source_row_no)
);

DO $$ BEGIN
  IF to_regclass('calc.dual_quote_result') IS NOT NULL THEN
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_auxiliary_version text;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_auxiliary_snapshot jsonb;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_auxiliary_catalog_v1(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_profile jsonb;v_line jsonb;v_profile_id bigint;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-auxiliary-[0-9a-f]{16}-v[0-9]+$' THEN RAISE EXCEPTION 'Invalid cabinet auxiliary data_version'; END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid source SHA-256'; END IF;
  IF jsonb_typeof(p_payload->'profiles')<>'array' OR jsonb_array_length(p_payload->'profiles')<>16 THEN RAISE EXCEPTION 'Expected exactly 16 auxiliary profiles'; END IF;
  IF jsonb_typeof(p_payload->'lines')<>'array' OR jsonb_array_length(p_payload->'lines')<>255 THEN RAISE EXCEPTION 'Expected exactly 255 auxiliary lines'; END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=v_version AND status='ACTIVE') THEN RAISE EXCEPTION 'Cannot overwrite ACTIVE auxiliary version %',v_version; END IF;
  DELETE FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=v_version;
  INSERT INTO calc.cabinet_auxiliary_catalog_version(data_version,source_file,source_sha256,status)
  VALUES(v_version,p_payload->>'source_file',p_payload->>'source_sha256','STAGED');
  FOR v_profile IN SELECT value FROM jsonb_array_elements(p_payload->'profiles') LOOP
    INSERT INTO calc.cabinet_auxiliary_profile(data_version,profile_key,product_code,single_door_count,double_door_count,
      source_sheet,source_summary_formula,source_cached_total)
    VALUES(v_version,v_profile->>'profile_key',v_profile->>'product_code',(v_profile->>'single_door_count')::integer,
      (v_profile->>'double_door_count')::integer,v_profile->>'source_sheet',v_profile->>'source_summary_formula',
      NULLIF(v_profile->>'source_cached_total','')::numeric) RETURNING profile_id INTO v_profile_id;
    FOR v_line IN SELECT value FROM jsonb_array_elements(p_payload->'lines') WHERE value->>'profile_key'=v_profile->>'profile_key' LOOP
      INSERT INTO calc.cabinet_auxiliary_line(profile_id,line_no,item_code,item_name,spec_model,material_name,quantity_rule,
        unit_price,cost_kind,length_formula,spray_width_m,notes,source_total_formula,source_cached_total,source_sheet,source_row_no)
      VALUES(v_profile_id,(v_line->>'line_no')::integer,NULLIF(v_line->>'item_code',''),v_line->>'item_name',NULLIF(v_line->>'spec_model',''),
        NULLIF(v_line->>'material_name',''),v_line->'quantity_rule',(v_line->>'unit_price')::numeric,v_line->>'cost_kind',
        NULLIF(v_line->>'length_formula',''),NULLIF(v_line->>'spray_width_m','')::numeric,NULLIF(v_line->>'notes',''),
        v_line->>'source_total_formula',NULLIF(v_line->>'source_cached_total','')::numeric,v_line->>'source_sheet',(v_line->>'source_row_no')::integer);
    END LOOP;
  END LOOP;
  SELECT count(*) INTO v_count FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id) WHERE p.data_version=v_version;
  IF v_count<>255 THEN RAISE EXCEPTION 'Staged auxiliary count %, expected 255',v_count; END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
    WHERE p.data_version=v_version AND quantity_rule->>'kind' NOT IN ('CONSTANT','HEIGHT_GT')) THEN RAISE EXCEPTION 'Unsupported auxiliary quantity rule'; END IF;
  RETURN v_version;
END $$;
REVOKE ALL ON FUNCTION calc.stage_cabinet_auxiliary_catalog_v1(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.activate_cabinet_auxiliary_catalog_v1(p_version text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_profiles integer;v_lines integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_auxiliary_catalog_version'));
  SELECT count(*) INTO v_profiles FROM calc.cabinet_auxiliary_profile p WHERE p.data_version=p_version;
  SELECT count(*) INTO v_lines FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
    WHERE p.data_version=p_version;
  IF NOT EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=p_version AND status='STAGED') OR v_profiles<>16 OR v_lines<>255
    THEN RAISE EXCEPTION 'Version % is not a complete STAGED auxiliary catalog',p_version; END IF;
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=p_version;
  RETURN p_version;
END $$;
REVOKE ALL ON FUNCTION calc.activate_cabinet_auxiliary_catalog_v1(text) FROM PUBLIC;
COMMIT;
