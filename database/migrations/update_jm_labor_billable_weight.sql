-- JM formula-labor catalog update confirmed by the user on 2026-09-14.
-- Change-spec SHA-256: 01249192a2981dc7af758e76f3e0c960cdbb6a3e128597f16a61a64bf4753fca
-- Both formulas use billable material weight, which is the current API behavior.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

DO $patch$
DECLARE
  v_source text;
  v_target constant text := 'cabinet-labor-01249192a2981dc7-v2';
  v_count integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.cabinet_labor_catalog_version'));

  IF EXISTS (
    SELECT 1 FROM calc.cabinet_labor_catalog_version
    WHERE data_version=v_target AND status='ACTIVE'
  ) THEN
    SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule
    WHERE data_version=v_target AND product_code='JM' AND rule_kind='LINEAR_WEIGHT';
    IF v_count<>2 THEN
      RAISE EXCEPTION 'Active target version % has % JM linear rules, expected 2',v_target,v_count;
    END IF;
    RAISE NOTICE 'JM labor catalog % is already active',v_target;
    RETURN;
  END IF;

  IF EXISTS (SELECT 1 FROM calc.cabinet_labor_catalog_version WHERE data_version=v_target) THEN
    RAISE EXCEPTION 'Target version % already exists but is not active',v_target;
  END IF;

  SELECT data_version INTO STRICT v_source
  FROM calc.cabinet_labor_catalog_version WHERE status='ACTIVE';
  IF v_source<>'cabinet-labor-a3d12580527a3eb6-v1' THEN
    RAISE EXCEPTION 'Unexpected active labor version %, expected cabinet-labor-a3d12580527a3eb6-v1',v_source;
  END IF;

  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule WHERE data_version=v_source;
  IF v_count<>57 THEN
    RAISE EXCEPTION 'Active source version % has % rules, expected 57',v_source,v_count;
  END IF;
  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule
  WHERE data_version=v_source AND product_code='JM' AND rule_kind='LINEAR_WEIGHT'
    AND material_codes='["SECC"]'::jsonb
    AND intercept=197.2715 AND slope=1.423229;
  IF v_count<>1 THEN
    RAISE EXCEPTION 'Expected exactly one original JM SECC labor rule, found %',v_count;
  END IF;

  INSERT INTO calc.cabinet_labor_catalog_version(
    data_version,source_file,source_sha256,status,management_fee_rate
  )
  SELECT v_target,
    source_file || '; JM人工公式修订（2026-09-14用户确认）',
    '01249192a2981dc7af758e76f3e0c960cdbb6a3e128597f16a61a64bf4753fca',
    'STAGED',management_fee_rate
  FROM calc.cabinet_labor_catalog_version WHERE data_version=v_source;

  INSERT INTO calc.cabinet_labor_rule(
    data_version,rule_kind,product_code,profile_code,material_codes,model_code,
    width_mm,height_mm,depth_mm,intercept,slope,excluded_part_names,labor_cost,
    allow_dimension_scale,source_formula,source_sheet,source_row_no
  )
  SELECT v_target,rule_kind,product_code,profile_code,material_codes,model_code,
    width_mm,height_mm,depth_mm,intercept,slope,excluded_part_names,labor_cost,
    allow_dimension_scale,source_formula,source_sheet,source_row_no
  FROM calc.cabinet_labor_rule WHERE data_version=v_source;

  UPDATE calc.cabinet_labor_rule
  SET excluded_part_names='[]'::jsonb,
      source_formula='人工 = 197.2715 + 1.423229 × 计价材料重量'
  WHERE data_version=v_target AND product_code='JM' AND rule_kind='LINEAR_WEIGHT'
    AND material_codes='["SECC"]'::jsonb;
  GET DIAGNOSTICS v_count=ROW_COUNT;
  IF v_count<>1 THEN RAISE EXCEPTION 'Updated % JM SECC rules, expected 1',v_count; END IF;

  INSERT INTO calc.cabinet_labor_rule(
    data_version,rule_kind,product_code,profile_code,material_codes,model_code,
    width_mm,height_mm,depth_mm,intercept,slope,excluded_part_names,labor_cost,
    allow_dimension_scale,source_formula,source_sheet,source_row_no
  ) VALUES (
    v_target,'LINEAR_WEIGHT','JM',NULL,'["SUS304","SUS316"]'::jsonb,NULL,
    NULL,NULL,NULL,292.5932,2.756249,'["安装板"]'::jsonb,NULL,false,
    '人工 = 292.5932 + 2.756249 × 计价材料重量（去掉安装板的重量）','JM',4
  );

  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule WHERE data_version=v_target;
  IF v_count<>58 THEN RAISE EXCEPTION 'Target version % has % rules, expected 58',v_target,v_count; END IF;
  SELECT count(*) INTO v_count FROM calc.cabinet_labor_rule
  WHERE data_version=v_target AND product_code='JM' AND rule_kind='LINEAR_WEIGHT'
    AND ((material_codes='["SECC"]'::jsonb AND excluded_part_names='[]'::jsonb)
      OR (material_codes='["SUS304","SUS316"]'::jsonb AND excluded_part_names='["安装板"]'::jsonb));
  IF v_count<>2 THEN RAISE EXCEPTION 'Target version has % JM billable-weight rules, expected 2',v_count; END IF;

  UPDATE calc.cabinet_labor_catalog_version
  SET status='RETIRED',activated_at=NULL WHERE status='ACTIVE';
  UPDATE calc.cabinet_labor_catalog_version
  SET status='ACTIVE',activated_at=current_timestamp WHERE data_version=v_target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Failed to activate target version %',v_target; END IF;
END
$patch$;
COMMIT;
