-- Replace executable management pricing; historical quote snapshots are untouched.
-- Re-runnable. No tables are dropped and no existing quote amounts are rewritten.
BEGIN;

CREATE OR REPLACE FUNCTION calc.calculate_total_cost(
  p_corrected_material_weight_kg NUMERIC,
  p_material_price_per_kg NUMERIC,
  p_auxiliary_cost NUMERIC DEFAULT 0,
  p_labor_cost NUMERIC DEFAULT 0,
  p_attachment_fee NUMERIC DEFAULT 0,
  p_product_area_m2 NUMERIC DEFAULT 0,
  p_spray_unit_price NUMERIC DEFAULT 0
)
RETURNS TABLE (
  material_cost NUMERIC,
  auxiliary_cost NUMERIC,
  labor_cost NUMERIC,
  attachment_fee NUMERIC,
  spray_cost NUMERIC,
  management_fee NUMERIC,
  total_cost NUMERIC
)
LANGUAGE SQL
IMMUTABLE
AS $function$
  -- The database base has zero freight; API/client rederive with actual freight.
  WITH components AS (
    SELECT ROUND(p_corrected_material_weight_kg * p_material_price_per_kg, 2) AS material_cost,
      ROUND(COALESCE(p_auxiliary_cost, 0), 2) AS auxiliary_cost,
      ROUND(COALESCE(p_labor_cost, 0), 2) AS labor_cost,
      ROUND(COALESCE(p_attachment_fee, 0), 2) AS attachment_fee,
      ROUND(COALESCE(p_product_area_m2, 0) * COALESCE(p_spray_unit_price, 0), 2) AS spray_cost
  ), fees AS (
    SELECT *, ROUND((material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost) * 0.06, 2) AS management_fee
    FROM components
  )
  SELECT material_cost, auxiliary_cost, labor_cost, attachment_fee, spray_cost, management_fee,
    material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost + management_fee AS total_cost
  FROM fees;
$function$;

CREATE OR REPLACE FUNCTION calc.calculate_total_cost_by_spray_cost(
  p_corrected_material_weight_kg NUMERIC,
  p_material_price_per_kg NUMERIC,
  p_auxiliary_cost NUMERIC DEFAULT 0,
  p_labor_cost NUMERIC DEFAULT 0,
  p_attachment_fee NUMERIC DEFAULT 0,
  p_spray_cost NUMERIC DEFAULT 0
)
RETURNS TABLE (
  material_cost NUMERIC,
  auxiliary_cost NUMERIC,
  labor_cost NUMERIC,
  attachment_fee NUMERIC,
  spray_cost NUMERIC,
  management_fee NUMERIC,
  total_cost NUMERIC
)
LANGUAGE SQL
IMMUTABLE
AS $function$
  -- The database base has zero freight; API/client rederive with actual freight.
  WITH components AS (
    SELECT ROUND(p_corrected_material_weight_kg * p_material_price_per_kg, 2) AS material_cost,
      ROUND(COALESCE(p_auxiliary_cost, 0), 2) AS auxiliary_cost,
      ROUND(COALESCE(p_labor_cost, 0), 2) AS labor_cost,
      ROUND(COALESCE(p_attachment_fee, 0), 2) AS attachment_fee,
      ROUND(COALESCE(p_spray_cost, 0), 2) AS spray_cost
  ), fees AS (
    SELECT *, ROUND((material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost) * 0.06, 2) AS management_fee
    FROM components
  )
  SELECT material_cost, auxiliary_cost, labor_cost, attachment_fee, spray_cost, management_fee,
    material_cost + auxiliary_cost + labor_cost + attachment_fee + spray_cost + management_fee AS total_cost
  FROM fees;
$function$;

CREATE OR REPLACE FUNCTION calc.stage_cabinet_labor_catalog_v1(p_payload jsonb)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,calc AS $$
DECLARE v_version text:=p_payload->>'data_version';v_rule jsonb;v_count integer;
BEGIN
  IF v_version IS NULL OR v_version!~'^cabinet-labor-[0-9a-f]{16}-v[0-9]+$' THEN RAISE EXCEPTION 'Invalid cabinet labor data_version'; END IF;
  IF p_payload->>'source_sha256' IS NULL OR p_payload->>'source_sha256'!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid source SHA-256'; END IF;
  IF jsonb_typeof(p_payload->'rules')<>'array' OR jsonb_array_length(p_payload->'rules')<>57 THEN RAISE EXCEPTION 'Expected exactly 57 labor rules'; END IF;
  IF (p_payload->>'management_fee_rate')::numeric IS DISTINCT FROM 0.06 THEN RAISE EXCEPTION 'Expected management fee rate 0.06'; END IF;
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

UPDATE calc.cabinet_labor_catalog_version
SET management_fee_rate=0.06 WHERE status IN ('ACTIVE','STAGED');

COMMENT ON FUNCTION calc.calculate_total_cost(NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC)
IS 'Management = (material + auxiliary + cabinet labor + attachments + spray + freight) * 0.06. Base SQL uses zero freight; API rederives with actual per-set freight.';
COMMENT ON FUNCTION calc.calculate_total_cost_by_spray_cost(NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC,NUMERIC)
IS 'Current management pricing: six components at 6%; base freight is zero, actual freight is included by API/client.';

DO $$
DECLARE v_fee numeric; v_total numeric;
BEGIN
  SELECT management_fee,total_cost INTO v_fee,v_total
  FROM calc.calculate_total_cost_by_spray_cost(1,826.52,49.60,332.54,720.88,80.65);
  IF v_fee IS DISTINCT FROM 120.61 OR v_total IS DISTINCT FROM 2130.80 THEN
    RAISE EXCEPTION 'Management fee migration validation failed: %, %',v_fee,v_total;
  END IF;
END $$;
COMMIT;

