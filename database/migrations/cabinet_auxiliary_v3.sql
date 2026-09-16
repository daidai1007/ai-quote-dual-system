-- Complete versioned cabinet auxiliary catalog with material-specific BOM profiles.
-- BOM source: 辅材BOM清单.xlsx
-- Fixed-price source: JK,JC,操作台辅材价格.xlsx
-- Formula quotation only; quick quotation is untouched.
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
ALTER TABLE calc.cabinet_auxiliary_catalog_version
  ADD COLUMN IF NOT EXISTS source_files jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_auxiliary_one_active
  ON calc.cabinet_auxiliary_catalog_version((status)) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS calc.cabinet_auxiliary_profile (
  profile_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_auxiliary_catalog_version(data_version) ON DELETE CASCADE,
  profile_key text NOT NULL,
  product_code text NOT NULL CHECK(product_code IN ('JA','JE','JS','JP','JM')),
  material_codes jsonb NOT NULL,
  single_door_count integer NOT NULL CHECK(single_door_count BETWEEN 0 AND 2),
  double_door_count integer NOT NULL CHECK(double_door_count BETWEEN 0 AND 2),
  source_sheet text NOT NULL,
  source_summary_formula text NOT NULL,
  source_cached_total numeric,
  UNIQUE(data_version,profile_key),UNIQUE(data_version,source_sheet)
);
ALTER TABLE calc.cabinet_auxiliary_profile ADD COLUMN IF NOT EXISTS material_codes jsonb;
UPDATE calc.cabinet_auxiliary_profile
SET material_codes='["SECC","SUS304","SUS316"]'::jsonb
WHERE material_codes IS NULL;
ALTER TABLE calc.cabinet_auxiliary_profile ALTER COLUMN material_codes SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='cabinet_auxiliary_profile_material_codes_check'
    AND conrelid='calc.cabinet_auxiliary_profile'::regclass) THEN
    ALTER TABLE calc.cabinet_auxiliary_profile ADD CONSTRAINT cabinet_auxiliary_profile_material_codes_check
      CHECK(jsonb_typeof(material_codes)='array' AND jsonb_array_length(material_codes)>0);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS cabinet_auxiliary_profile_lookup
  ON calc.cabinet_auxiliary_profile(data_version,product_code,single_door_count,double_door_count);
CREATE INDEX IF NOT EXISTS cabinet_auxiliary_profile_material_lookup
  ON calc.cabinet_auxiliary_profile USING gin(material_codes);

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

CREATE TABLE IF NOT EXISTS calc.cabinet_auxiliary_fixed_rule (
  rule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_auxiliary_catalog_version(data_version) ON DELETE CASCADE,
  product_code text NOT NULL CHECK(product_code IN ('JK','JC_EXP','JQ_EXP','JP_WIDE_EXP','JS_WIDE_EXP','OP_TABLE_EXP')),
  profile_code text,
  material_codes jsonb NOT NULL CHECK(jsonb_typeof(material_codes)='array' AND jsonb_array_length(material_codes)>0),
  model_code text,
  width_mm numeric NOT NULL CHECK(width_mm>0),
  height_mm numeric NOT NULL CHECK(height_mm>0),
  depth_mm numeric NOT NULL CHECK(depth_mm>0),
  auxiliary_cost numeric NOT NULL CHECK(auxiliary_cost>=0),
  allow_dimension_scale boolean NOT NULL DEFAULT true,
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK(source_row_no>0),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  UNIQUE(data_version,source_sheet,source_row_no)
);
CREATE INDEX IF NOT EXISTS cabinet_auxiliary_fixed_rule_lookup
  ON calc.cabinet_auxiliary_fixed_rule(data_version,product_code,profile_code,model_code);

DO $$ BEGIN
  IF to_regclass('calc.dual_quote_result') IS NOT NULL THEN
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_auxiliary_version text;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_auxiliary_snapshot jsonb;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_auxiliary_catalog_v3(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_profile jsonb;v_line jsonb;v_rule jsonb;v_profile_id bigint;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-auxiliary-[0-9a-f]{16}-v3$' THEN RAISE EXCEPTION 'Invalid cabinet auxiliary V3 data_version'; END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid combined source SHA-256'; END IF;
  IF jsonb_typeof(p_payload->'source_files')<>'array' OR jsonb_array_length(p_payload->'source_files')<>2 THEN RAISE EXCEPTION 'Expected exactly two auxiliary source files'; END IF;
  IF jsonb_typeof(p_payload->'profiles')<>'array' OR jsonb_array_length(p_payload->'profiles')<>32 THEN RAISE EXCEPTION 'Expected exactly 32 material-specific auxiliary profiles'; END IF;
  IF jsonb_typeof(p_payload->'lines')<>'array' OR jsonb_array_length(p_payload->'lines')<>510 THEN RAISE EXCEPTION 'Expected exactly 510 auxiliary lines'; END IF;
  IF jsonb_typeof(p_payload->'fixed_rules')<>'array' OR jsonb_array_length(p_payload->'fixed_rules')<>72 THEN RAISE EXCEPTION 'Expected exactly 72 fixed auxiliary rules'; END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=v_version AND status='ACTIVE') THEN RAISE EXCEPTION 'Cannot overwrite ACTIVE auxiliary version %',v_version; END IF;
  DELETE FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=v_version;
  INSERT INTO calc.cabinet_auxiliary_catalog_version(data_version,source_file,source_sha256,source_files,status)
  VALUES(v_version,p_payload->>'source_file',p_payload->>'source_sha256',p_payload->'source_files','STAGED');
  FOR v_profile IN SELECT value FROM jsonb_array_elements(p_payload->'profiles') LOOP
    IF jsonb_typeof(v_profile->'material_codes')<>'array' OR jsonb_array_length(v_profile->'material_codes')=0 THEN
      RAISE EXCEPTION 'Auxiliary profile % has no material codes',v_profile->>'profile_key';
    END IF;
    INSERT INTO calc.cabinet_auxiliary_profile(data_version,profile_key,product_code,material_codes,single_door_count,double_door_count,
      source_sheet,source_summary_formula,source_cached_total)
    VALUES(v_version,v_profile->>'profile_key',v_profile->>'product_code',v_profile->'material_codes',(v_profile->>'single_door_count')::integer,
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
  FOR v_rule IN SELECT value FROM jsonb_array_elements(p_payload->'fixed_rules') LOOP
    INSERT INTO calc.cabinet_auxiliary_fixed_rule(data_version,product_code,profile_code,material_codes,model_code,
      width_mm,height_mm,depth_mm,auxiliary_cost,allow_dimension_scale,source_sheet,source_row_no)
    VALUES(v_version,v_rule->>'product_code',NULLIF(v_rule->>'profile_code',''),v_rule->'material_codes',NULLIF(v_rule->>'model_code',''),
      (v_rule->>'width_mm')::numeric,(v_rule->>'height_mm')::numeric,(v_rule->>'depth_mm')::numeric,
      (v_rule->>'auxiliary_cost')::numeric,coalesce((v_rule->>'allow_dimension_scale')::boolean,true),
      v_rule->>'source_sheet',(v_rule->>'source_row_no')::integer);
  END LOOP;
  SELECT count(*) INTO v_count FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id) WHERE p.data_version=v_version;
  IF v_count<>510 THEN RAISE EXCEPTION 'Staged auxiliary line count %, expected 510',v_count; END IF;
  SELECT count(*) INTO v_count FROM calc.cabinet_auxiliary_fixed_rule WHERE data_version=v_version;
  IF v_count<>72 THEN RAISE EXCEPTION 'Staged auxiliary fixed count %, expected 72',v_count; END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id)
    WHERE p.data_version=v_version AND quantity_rule->>'kind' NOT IN ('CONSTANT','HEIGHT_GT')) THEN RAISE EXCEPTION 'Unsupported auxiliary quantity rule'; END IF;
  RETURN v_version;
END $$;
REVOKE ALL ON FUNCTION calc.stage_cabinet_auxiliary_catalog_v3(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.activate_cabinet_auxiliary_catalog_v3(p_version text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_profiles integer;v_lines integer;v_fixed integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_auxiliary_catalog_version'));
  SELECT count(*) INTO v_profiles FROM calc.cabinet_auxiliary_profile p WHERE p.data_version=p_version;
  SELECT count(*) INTO v_lines FROM calc.cabinet_auxiliary_line l JOIN calc.cabinet_auxiliary_profile p USING(profile_id) WHERE p.data_version=p_version;
  SELECT count(*) INTO v_fixed FROM calc.cabinet_auxiliary_fixed_rule WHERE data_version=p_version;
  IF NOT EXISTS(SELECT 1 FROM calc.cabinet_auxiliary_catalog_version WHERE data_version=p_version AND status='STAGED')
     OR v_profiles<>32 OR v_lines<>510 OR v_fixed<>72
    THEN RAISE EXCEPTION 'Version % is not a complete STAGED auxiliary V3 catalog',p_version; END IF;
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_auxiliary_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=p_version;
  RETURN p_version;
END $$;
REVOKE ALL ON FUNCTION calc.activate_cabinet_auxiliary_catalog_v3(text) FROM PUBLIC;

-- Keep the DB-owned base quote function valid after the legacy auxiliary tables
-- are removed. The API replaces this base value with the dynamic V3 result.
CREATE OR REPLACE FUNCTION calc.get_auxiliary_cost(
  p_product_code VARCHAR,
  p_variant_code VARCHAR DEFAULT 'DEFAULT',
  p_model_code VARCHAR DEFAULT '',
  p_material_code VARCHAR DEFAULT NULL,
  p_width_mm INTEGER DEFAULT NULL,
  p_height_mm INTEGER DEFAULT NULL,
  p_depth_mm INTEGER DEFAULT NULL
)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $function$
DECLARE
  v_product text:=upper(btrim(coalesce(p_product_code,'')));
  v_variant text:=upper(btrim(coalesce(nullif(p_variant_code,''),'DEFAULT')));
  v_profile text;
  v_match record;
  v_cost numeric;
  v_ratio numeric:=1;
BEGIN
  v_product:=CASE v_product
    WHEN 'JC' THEN 'JC_EXP' WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP_WIDE' THEN 'JP_WIDE_EXP' WHEN 'JS_WIDE' THEN 'JS_WIDE_EXP'
    WHEN 'OP_TABLE' THEN 'OP_TABLE_EXP' ELSE v_product END;
  IF v_product='JC_EXP' THEN
    v_profile:=CASE
      WHEN v_variant~'(LUXURY|DELUXE)' OR coalesce(p_model_code,'')~'-1$' THEN 'LUXURY'
      WHEN v_variant~'(STANDARD|DEFAULT)' OR coalesce(p_model_code,'')~'-2$' THEN 'STANDARD'
      ELSE NULL END;
  END IF;
  IF p_width_mm IS NOT NULL AND p_height_mm IS NOT NULL AND p_depth_mm IS NOT NULL THEN
    SELECT r.* INTO v_match
    FROM calc.cabinet_auxiliary_fixed_rule r
    JOIN calc.cabinet_auxiliary_catalog_version v USING(data_version)
    WHERE v.status='ACTIVE' AND r.product_code=v_product AND r.material_codes ? p_material_code
      AND (v_product<>'JC_EXP' OR r.profile_code=v_profile)
    ORDER BY (r.width_mm=p_width_mm AND r.height_mm=p_height_mm AND r.depth_mm=p_depth_mm) DESC,
      abs((r.width_mm+r.height_mm+r.depth_mm)-(p_width_mm+p_height_mm+p_depth_mm)),
      power(r.width_mm-p_width_mm,2)+power(r.height_mm-p_height_mm,2)+power(r.depth_mm-p_depth_mm,2),r.rule_id DESC
    LIMIT 1;
    IF FOUND THEN
      IF NOT (v_match.width_mm=p_width_mm AND v_match.height_mm=p_height_mm AND v_match.depth_mm=p_depth_mm) THEN
        IF NOT v_match.allow_dimension_scale THEN RETURN NULL; END IF;
        v_ratio:=(p_width_mm+p_height_mm+p_depth_mm)::numeric/(v_match.width_mm+v_match.height_mm+v_match.depth_mm);
      END IF;
      RETURN round(v_match.auxiliary_cost*v_ratio,6);
    END IF;
  END IF;
  SELECT p.source_cached_total INTO v_cost
  FROM calc.cabinet_auxiliary_profile p JOIN calc.cabinet_auxiliary_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND p.product_code=v_product
    AND p.material_codes ? upper(btrim(coalesce(p_material_code,'')))
    AND (CASE v_variant WHEN 'DOUBLE' THEN p.single_door_count=0 AND p.double_door_count=1
                        ELSE p.single_door_count=1 AND p.double_door_count=0 END)
  ORDER BY p.profile_id DESC LIMIT 1;
  RETURN v_cost;
END;
$function$;

COMMIT;
