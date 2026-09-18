-- Complete versioned cabinet material catalog: formula details plus experience weights.
-- Additive: this migration does not activate a catalog or delete legacy data.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE TABLE IF NOT EXISTS calc.cabinet_material_catalog_version (
  data_version text PRIMARY KEY,
  source_file text NOT NULL,
  source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
  source_files jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(source_files)='array'),
  status text NOT NULL CHECK(status IN ('STAGED','ACTIVE','RETIRED')),
  default_waste_factor numeric NOT NULL CHECK(default_waste_factor>0 AND default_waste_factor<=10),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  activated_at timestamptz,
  CHECK((status='ACTIVE')=(activated_at IS NOT NULL))
);
ALTER TABLE calc.cabinet_material_catalog_version
  ADD COLUMN IF NOT EXISTS source_files jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_material_one_active
  ON calc.cabinet_material_catalog_version((status)) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS calc.cabinet_material_rule (
  rule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_material_catalog_version(data_version) ON DELETE CASCADE,
  family text NOT NULL CHECK(family IN ('JS','JP','JA','JE','JK','JM')),
  body_thickness_profile_mm numeric,
  profile_label text NOT NULL,
  single_door_count integer NOT NULL CHECK(single_door_count BETWEEN 0 AND 2),
  double_door_count integer NOT NULL CHECK(double_door_count BETWEEN 0 AND 2),
  part_name text NOT NULL CHECK(btrim(part_name)<>''),
  area_formula text NOT NULL CHECK(btrim(area_formula)<>''),
  sheet_thickness_mm numeric NOT NULL CHECK(sheet_thickness_mm>0),
  quantity_rule jsonb NOT NULL CHECK(jsonb_typeof(quantity_rule)='object'),
  fixed_material_code text,
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK(source_row_no>0),
  source_column text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  UNIQUE(data_version,source_sheet,source_row_no,source_column)
);
CREATE INDEX IF NOT EXISTS cabinet_material_rule_lookup
  ON calc.cabinet_material_rule(data_version,family,single_door_count,double_door_count,body_thickness_profile_mm);
COMMENT ON TABLE calc.cabinet_material_rule IS
  'Formula-product net material rules. Their net weights use the operator waste factor for billable weight.';

CREATE TABLE IF NOT EXISTS calc.cabinet_material_fixed_rule (
  fixed_rule_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  data_version text NOT NULL REFERENCES calc.cabinet_material_catalog_version(data_version) ON DELETE CASCADE,
  product_code text NOT NULL CHECK(product_code IN ('JC_EXP','JQ_EXP','JP_WIDE_EXP','JS_WIDE_EXP','OP_TABLE_EXP')),
  profile_code text,
  material_codes jsonb NOT NULL CHECK(jsonb_typeof(material_codes)='array' AND jsonb_array_length(material_codes)>0),
  model_code text NOT NULL CHECK(btrim(model_code)<>''),
  width_mm numeric NOT NULL CHECK(width_mm>0),
  height_mm numeric NOT NULL CHECK(height_mm>0),
  depth_mm numeric NOT NULL CHECK(depth_mm>0),
  material_weight_kg numeric NOT NULL CHECK(material_weight_kg>0),
  allow_dimension_scale boolean NOT NULL DEFAULT true,
  apply_waste_factor boolean NOT NULL DEFAULT false CHECK(apply_waste_factor=false),
  source_sheet text NOT NULL,
  source_row_no integer NOT NULL CHECK(source_row_no>0),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  UNIQUE(data_version,source_sheet,source_row_no),
  UNIQUE(data_version,product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm)
);
CREATE INDEX IF NOT EXISTS cabinet_material_fixed_lookup
  ON calc.cabinet_material_fixed_rule(data_version,product_code,profile_code,width_mm,height_mm,depth_mm);
CREATE UNIQUE INDEX IF NOT EXISTS cabinet_material_fixed_identity_unique
  ON calc.cabinet_material_fixed_rule(data_version,product_code,profile_code,material_codes,model_code,width_mm,height_mm,depth_mm)
  NULLS NOT DISTINCT;
COMMENT ON TABLE calc.cabinet_material_fixed_rule IS
  'Experience-product weights. Non-standard dimensions use the established (W+H+D) ratio; waste factor never applies.';

DO $$ BEGIN
  IF to_regclass('calc.dual_quote_result') IS NOT NULL THEN
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS formula_net_material_weight_kg numeric;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS formula_corrected_material_weight_kg numeric;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS formula_waste_factor numeric;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_material_version text;
    ALTER TABLE calc.dual_quote_result ADD COLUMN IF NOT EXISTS cabinet_material_snapshot jsonb;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_material_catalog_v2(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_rule jsonb;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-material-[0-9a-f]{16}-v2$' THEN
    RAISE EXCEPTION 'Invalid cabinet material V2 data_version';
  END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'Invalid cabinet material source SHA-256';
  END IF;
  IF jsonb_typeof(p_payload->'source_files')<>'array' OR jsonb_array_length(p_payload->'source_files')<>2 THEN
    RAISE EXCEPTION 'Expected exactly two cabinet material source files';
  END IF;
  IF jsonb_typeof(p_payload->'rules')<>'array' OR jsonb_array_length(p_payload->'rules')<>241 THEN
    RAISE EXCEPTION 'Expected exactly 241 cabinet material area rules';
  END IF;
  IF jsonb_typeof(p_payload->'fixed_rules')<>'array' OR jsonb_array_length(p_payload->'fixed_rules')<>46 THEN
    RAISE EXCEPTION 'Expected exactly 46 cabinet material fixed rules';
  END IF;
  IF (p_payload->>'default_waste_factor')::numeric<>1.2 THEN
    RAISE EXCEPTION 'Source default waste factor must be 1.2';
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_material_catalog_version WHERE data_version=v_version AND status='ACTIVE') THEN
    RAISE EXCEPTION 'Cannot overwrite ACTIVE cabinet material version %',v_version;
  END IF;
  DELETE FROM calc.cabinet_material_catalog_version WHERE data_version=v_version;
  INSERT INTO calc.cabinet_material_catalog_version(data_version,source_file,source_sha256,source_files,status,default_waste_factor)
  VALUES(v_version,p_payload->>'source_file',p_payload->>'source_sha256',p_payload->'source_files','STAGED',
    (p_payload->>'default_waste_factor')::numeric);
  FOR v_rule IN SELECT value FROM jsonb_array_elements(p_payload->'rules') LOOP
    INSERT INTO calc.cabinet_material_rule(data_version,family,body_thickness_profile_mm,profile_label,
      single_door_count,double_door_count,part_name,area_formula,sheet_thickness_mm,quantity_rule,
      fixed_material_code,source_sheet,source_row_no,source_column)
    VALUES(v_version,v_rule->>'family',NULLIF(v_rule->>'body_thickness_profile_mm','')::numeric,
      v_rule->>'profile_label',(v_rule->>'single_door_count')::integer,(v_rule->>'double_door_count')::integer,
      v_rule->>'part_name',v_rule->>'area_formula',(v_rule->>'sheet_thickness_mm')::numeric,
      v_rule->'quantity_rule',NULLIF(v_rule->>'fixed_material_code',''),v_rule->>'source_sheet',
      (v_rule->>'source_row_no')::integer,v_rule->>'source_column');
  END LOOP;
  FOR v_rule IN SELECT value FROM jsonb_array_elements(p_payload->'fixed_rules') LOOP
    INSERT INTO calc.cabinet_material_fixed_rule(data_version,product_code,profile_code,material_codes,model_code,
      width_mm,height_mm,depth_mm,material_weight_kg,allow_dimension_scale,apply_waste_factor,source_sheet,source_row_no)
    VALUES(v_version,v_rule->>'product_code',NULLIF(v_rule->>'profile_code',''),v_rule->'material_codes',v_rule->>'model_code',
      (v_rule->>'width_mm')::numeric,(v_rule->>'height_mm')::numeric,(v_rule->>'depth_mm')::numeric,
      (v_rule->>'material_weight_kg')::numeric,coalesce((v_rule->>'allow_dimension_scale')::boolean,true),
      coalesce((v_rule->>'apply_waste_factor')::boolean,false),v_rule->>'source_sheet',(v_rule->>'source_row_no')::integer);
  END LOOP;
  SELECT count(*) INTO v_count FROM calc.cabinet_material_rule WHERE data_version=v_version;
  IF v_count<>241 OR (SELECT count(DISTINCT family) FROM calc.cabinet_material_rule WHERE data_version=v_version)<>6 THEN
    RAISE EXCEPTION 'Staged cabinet material area catalog is incomplete';
  END IF;
  SELECT count(*) INTO v_count FROM calc.cabinet_material_fixed_rule WHERE data_version=v_version;
  IF v_count<>46 OR (SELECT count(DISTINCT product_code) FROM calc.cabinet_material_fixed_rule WHERE data_version=v_version)<>5 THEN
    RAISE EXCEPTION 'Staged cabinet material fixed catalog is incomplete';
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_material_rule WHERE data_version=v_version
    AND (quantity_rule->>'kind') NOT IN ('CONSTANT','JS_DEPTH_HEIGHT','HEIGHT_GT','WIDTH_GT','JE_REINFORCEMENT')) THEN
    RAISE EXCEPTION 'Unsupported cabinet material quantity rule';
  END IF;
  IF EXISTS(SELECT 1 FROM calc.cabinet_material_fixed_rule WHERE data_version=v_version AND apply_waste_factor) THEN
    RAISE EXCEPTION 'Experience material weights must not apply the waste factor';
  END IF;
  RETURN v_version;
END $$;
REVOKE ALL ON FUNCTION calc.stage_cabinet_material_catalog_v2(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.activate_cabinet_material_catalog_v2(p_version text)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_area integer;v_families integer;v_fixed integer;v_products integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_material_catalog_version'));
  SELECT count(*),count(DISTINCT family) INTO v_area,v_families FROM calc.cabinet_material_rule WHERE data_version=p_version;
  SELECT count(*),count(DISTINCT product_code) INTO v_fixed,v_products FROM calc.cabinet_material_fixed_rule WHERE data_version=p_version;
  IF NOT EXISTS(SELECT 1 FROM calc.cabinet_material_catalog_version WHERE data_version=p_version AND status='STAGED')
     OR v_area<>241 OR v_families<>6 OR v_fixed<>46 OR v_products<>5 THEN
    RAISE EXCEPTION 'Version % is not a complete STAGED cabinet material V2 catalog',p_version;
  END IF;
  UPDATE calc.cabinet_material_catalog_version SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_material_catalog_version SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=p_version;
  RETURN p_version;
END $$;
REVOKE ALL ON FUNCTION calc.activate_cabinet_material_catalog_v2(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION calc.get_cabinet_material_fixed_weight(
  p_product_code varchar,p_model_code varchar,p_material_code varchar,
  p_width_mm numeric,p_height_mm numeric,p_depth_mm numeric
)
RETURNS numeric LANGUAGE plpgsql STABLE SET search_path=pg_catalog,calc AS $$
DECLARE v_product text:=upper(btrim(coalesce(p_product_code,'')));v_material text:=upper(btrim(coalesce(p_material_code,'')));
  v_profile text;v_match record;v_ratio numeric:=1;v_weight numeric;v_target_density numeric;v_base_density numeric;
BEGIN
  v_product:=CASE v_product WHEN 'JC' THEN 'JC_EXP' WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP_WIDE' THEN 'JP_WIDE_EXP' WHEN 'JP WIDE' THEN 'JP_WIDE_EXP'
    WHEN 'JS_WIDE' THEN 'JS_WIDE_EXP' WHEN 'JS WIDE' THEN 'JS_WIDE_EXP'
    WHEN 'OP_TABLE' THEN 'OP_TABLE_EXP' WHEN 'OP TABLE' THEN 'OP_TABLE_EXP' ELSE v_product END;
  IF v_product='JC_EXP' THEN
    v_profile:=CASE WHEN coalesce(p_model_code,'')~'-1$' THEN 'LUXURY'
                    WHEN coalesce(p_model_code,'')~'-2$' THEN 'STANDARD' ELSE NULL END;
  END IF;
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL THEN RETURN NULL; END IF;
  SELECT r.*,(r.material_codes ? v_material) AS direct_material INTO v_match
  FROM calc.cabinet_material_fixed_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.product_code=v_product
    AND (v_product<>'JC_EXP' OR v_profile IS NULL OR r.profile_code=v_profile)
    AND (r.material_codes ? v_material OR (v_material IN ('SUS304','SUS316') AND r.material_codes ? 'SECC'))
  ORDER BY (r.material_codes ? v_material) DESC,
    (r.width_mm=p_width_mm AND r.height_mm=p_height_mm AND r.depth_mm=p_depth_mm) DESC,
    abs((r.width_mm+r.height_mm+r.depth_mm)-(p_width_mm+p_height_mm+p_depth_mm)),
    power(r.width_mm-p_width_mm,2)+power(r.height_mm-p_height_mm,2)+power(r.depth_mm-p_depth_mm,2),r.fixed_rule_id DESC
  LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF NOT (v_match.width_mm=p_width_mm AND v_match.height_mm=p_height_mm AND v_match.depth_mm=p_depth_mm) THEN
    IF NOT v_match.allow_dimension_scale THEN RETURN NULL; END IF;
    v_ratio:=(p_width_mm+p_height_mm+p_depth_mm)/(v_match.width_mm+v_match.height_mm+v_match.depth_mm);
  END IF;
  v_weight:=v_match.material_weight_kg*v_ratio;
  IF v_match.direct_material THEN RETURN round(v_weight,6); END IF;
  SELECT density_g_cm3 INTO v_target_density FROM calc.material WHERE material_code=v_material;
  SELECT density_g_cm3 INTO v_base_density FROM calc.material WHERE material_code='SECC';
  IF v_target_density IS NULL OR v_base_density IS NULL OR v_base_density=0 THEN RETURN NULL; END IF;
  RETURN round(v_weight*v_target_density/v_base_density,6);
END $$;
COMMENT ON FUNCTION calc.get_cabinet_material_fixed_weight(varchar,varchar,varchar,numeric,numeric,numeric)
IS 'Active V2 experience weight. Uses nearest dimensions and perimeter scaling; never applies waste factor.';

CREATE OR REPLACE FUNCTION calc.get_experience_material_weight_by_dimension(
  p_product_code varchar,p_material_code varchar,p_width_mm numeric,p_height_mm numeric,p_depth_mm numeric
)
RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT calc.get_cabinet_material_fixed_weight($1,'',$2,$3,$4,$5)
$$;

CREATE OR REPLACE FUNCTION calc.get_corrected_material_weight_kg(
  p_product_code varchar,p_model_code varchar,p_material_code varchar,
  p_width_mm numeric,p_height_mm numeric,p_depth_mm numeric,p_base_material_weight_kg numeric DEFAULT NULL
)
RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE v_target_density numeric;v_base_density numeric;
BEGIN
  IF p_base_material_weight_kg IS NULL THEN
    RETURN calc.get_cabinet_material_fixed_weight(
      p_product_code,p_model_code,p_material_code,p_width_mm,p_height_mm,p_depth_mm);
  END IF;
  IF p_material_code='SECC' THEN RETURN p_base_material_weight_kg; END IF;
  SELECT density_g_cm3 INTO v_target_density FROM calc.material WHERE material_code=p_material_code;
  SELECT density_g_cm3 INTO v_base_density FROM calc.material WHERE material_code='SECC';
  IF v_target_density IS NULL OR v_base_density IS NULL OR v_base_density=0 THEN RETURN NULL; END IF;
  RETURN round(p_base_material_weight_kg*v_target_density/v_base_density,6);
END $$;

CREATE OR REPLACE FUNCTION calc.get_corrected_material_weight_kg(
  p_product_code varchar,p_model_code varchar,p_material_code varchar,p_base_material_weight_kg numeric DEFAULT NULL
)
RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE v_rule record;v_product text:=upper(btrim(coalesce(p_product_code,'')));
BEGIN
  IF p_base_material_weight_kg IS NOT NULL THEN
    RETURN calc.get_corrected_material_weight_kg($1,$2,$3,NULL,NULL,NULL,$4);
  END IF;
  v_product:=CASE v_product WHEN 'JC' THEN 'JC_EXP' WHEN 'JQ' THEN 'JQ_EXP'
    WHEN 'JP_WIDE' THEN 'JP_WIDE_EXP' WHEN 'JS_WIDE' THEN 'JS_WIDE_EXP'
    WHEN 'OP_TABLE' THEN 'OP_TABLE_EXP' ELSE v_product END;
  SELECT r.width_mm,r.height_mm,r.depth_mm INTO v_rule
  FROM calc.cabinet_material_fixed_rule r JOIN calc.cabinet_material_catalog_version v USING(data_version)
  WHERE v.status='ACTIVE' AND r.product_code=v_product AND (r.model_code=p_model_code OR p_model_code IS NULL OR p_model_code='')
  ORDER BY (r.model_code=p_model_code) DESC,(r.material_codes ? upper(btrim(coalesce(p_material_code,'')))) DESC,r.fixed_rule_id DESC LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  RETURN calc.get_cabinet_material_fixed_weight($1,$2,$3,v_rule.width_mm,v_rule.height_mm,v_rule.depth_mm);
END $$;

COMMIT;
