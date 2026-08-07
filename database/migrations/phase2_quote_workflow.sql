/*
  V1.1 / Phase 2: quote API contract and workflow.
  The database remains the single source of truth for cost calculation.
  Run after the V1.0 functions and attachment-selection script.
*/
BEGIN;

CREATE TABLE IF NOT EXISTS calc.quote_request (
  quote_id VARCHAR(80) PRIMARY KEY,
  status VARCHAR(24) NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','calculated','confirmed','submitted','approved','rejected')),
  product_code VARCHAR(40) NOT NULL,
  model_code VARCHAR(100),
  variant_code VARCHAR(40),
  material_code VARCHAR(30) NOT NULL,
  width_mm NUMERIC(12,3) NOT NULL CHECK (width_mm > 0),
  height_mm NUMERIC(12,3) NOT NULL CHECK (height_mm > 0),
  depth_mm NUMERIC(12,3) NOT NULL CHECK (depth_mm > 0),
  base_material_weight_kg NUMERIC(14,6),
  product_area_m2 NUMERIC(14,6),
  coating_type VARCHAR(40),
  quote_date DATE NOT NULL DEFAULT CURRENT_DATE,
  risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_by VARCHAR(80),
  confirmed_by VARCHAR(80),
  submitted_by VARCHAR(80),
  approved_by VARCHAR(80),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  calculated_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  approved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_quote_request_status
  ON calc.quote_request(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_quote_request_product
  ON calc.quote_request(product_code, model_code, material_code);

/* Existing V1.0 result table is retained; these columns make it API/audit ready. */
ALTER TABLE calc.calculation_result
  ADD COLUMN IF NOT EXISTS workflow_quote_id VARCHAR(80),
  ADD COLUMN IF NOT EXISTS workflow_status VARCHAR(24) DEFAULT 'calculated',
  ADD COLUMN IF NOT EXISTS input_width_mm NUMERIC(12,3),
  ADD COLUMN IF NOT EXISTS input_height_mm NUMERIC(12,3),
  ADD COLUMN IF NOT EXISTS input_depth_mm NUMERIC(12,3),
  ADD COLUMN IF NOT EXISTS coating_type VARCHAR(40),
  ADD COLUMN IF NOT EXISTS quote_date DATE,
  ADD COLUMN IF NOT EXISTS risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS calculated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_calculation_result_workflow_quote
  ON calc.calculation_result(workflow_quote_id, calculated_at DESC);

CREATE OR REPLACE VIEW calc.v_quote_workflow AS
SELECT q.quote_id, q.status,
       CASE q.status
         WHEN 'draft' THEN '草稿'
         WHEN 'calculated' THEN '已计算'
         WHEN 'confirmed' THEN '人工确认'
         WHEN 'submitted' THEN '提交审核'
         WHEN 'approved' THEN '审核通过'
         WHEN 'rejected' THEN '已退回'
       END AS status_name,
       q.product_code, q.model_code, q.variant_code, q.material_code,
       q.width_mm, q.height_mm, q.depth_mm,
       q.base_material_weight_kg, q.product_area_m2, q.coating_type,
       q.quote_date, q.risk_flags, q.created_by, q.created_at,
       q.updated_at, q.calculated_at, q.confirmed_at,
       q.submitted_at, q.approved_at
FROM calc.quote_request q;

CREATE OR REPLACE FUNCTION calc.calculate_quote_api(
  p_quote_id VARCHAR,
  p_product_code VARCHAR,
  p_model_code VARCHAR DEFAULT NULL,
  p_variant_code VARCHAR DEFAULT NULL,
  p_width_mm NUMERIC DEFAULT NULL,
  p_height_mm NUMERIC DEFAULT NULL,
  p_depth_mm NUMERIC DEFAULT NULL,
  p_material_code VARCHAR DEFAULT 'SECC',
  p_base_material_weight_kg NUMERIC DEFAULT NULL,
  p_product_area_m2 NUMERIC DEFAULT NULL,
  p_coating_type VARCHAR DEFAULT U&'\5E73\5149',
  p_quote_date DATE DEFAULT CURRENT_DATE,
  p_created_by VARCHAR DEFAULT NULL
)
RETURNS TABLE (
  quote_id VARCHAR,
  status VARCHAR,
  product_code VARCHAR,
  model_code VARCHAR,
  material_code VARCHAR,
  corrected_material_weight_kg NUMERIC,
  material_cost NUMERIC,
  auxiliary_cost NUMERIC,
  labor_cost NUMERIC,
  attachment_fee NUMERIC,
  product_area_m2 NUMERIC,
  spray_cost NUMERIC,
  management_fee NUMERIC,
  total_cost NUMERIC,
  risk_flags JSONB
)
LANGUAGE plpgsql
VOLATILE
AS $function$
DECLARE
  v_product_code VARCHAR := CASE p_product_code
    WHEN 'JC' THEN 'JC_EXP'
    WHEN 'JQ' THEN 'JQ_EXP'
    WHEN U&'\8D85\5BBDJP' THEN 'JP_WIDE_EXP'
    WHEN U&'\8D85\5BBDJS' THEN 'JS_WIDE_EXP'
    WHEN U&'\64CD\4F5C\53F0' THEN 'OP_TABLE_EXP'
    ELSE p_product_code END;
  v_aux_product_code VARCHAR;
  v_aux_variant VARCHAR;
  v_aux_model VARCHAR;
  v_is_template BOOLEAN;
  v_is_experience BOOLEAN;
  v_material_price NUMERIC;
  v_auxiliary NUMERIC;
  v_labor NUMERIC;
  v_labor_detail RECORD;
  v_spray NUMERIC;
  v_attachment NUMERIC;
  v_weight NUMERIC;
  v_result RECORD;
  v_risks JSONB := '[]'::jsonb;
  v_unpriced_attachment_count INTEGER;
BEGIN
  IF p_quote_id IS NULL OR btrim(p_quote_id) = '' THEN
    RAISE EXCEPTION 'quote_id is required';
  END IF;
  IF p_width_mm IS NULL OR p_height_mm IS NULL OR p_depth_mm IS NULL
     OR p_width_mm <= 0 OR p_height_mm <= 0 OR p_depth_mm <= 0 THEN
    RAISE EXCEPTION 'width, height and depth must be positive';
  END IF;
  IF p_material_code NOT IN ('SECC','SUS304','SUS316') THEN
    RAISE EXCEPTION 'unsupported material_code: %', p_material_code;
  END IF;

  SELECT EXISTS (SELECT 1 FROM calc.cabinet_template WHERE template_code = v_product_code)
    INTO v_is_template;
  SELECT EXISTS (SELECT 1 FROM calc.experience_product WHERE product_code = v_product_code)
    INTO v_is_experience;
  IF NOT v_is_template AND NOT v_is_experience THEN
    RAISE EXCEPTION 'unsupported product_code: %', p_product_code;
  END IF;

  IF v_is_template AND (p_base_material_weight_kg IS NULL OR p_product_area_m2 IS NULL) THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','template_input_missing','severity','blocker',
      'message','公式柜型必须提供公式引擎计算的基准重量和产品面积'));
  END IF;

  v_aux_product_code := CASE v_product_code
    WHEN 'JS_SINGLE' THEN 'JS'
    WHEN 'JS_DOUBLE' THEN 'JS'
    WHEN 'JP_SINGLE' THEN 'JP'
    WHEN 'JP_DOUBLE' THEN 'JP'
    WHEN 'JA_SINGLE' THEN 'JA'
    WHEN 'JE_SINGLE' THEN 'JE'
    WHEN 'JE_DOUBLE' THEN 'JE'
    WHEN 'JM' THEN 'JM'
    ELSE v_product_code END;
  v_aux_variant := COALESCE(NULLIF(p_variant_code,''), CASE
    WHEN v_product_code IN ('JS_SINGLE','JP_SINGLE','JE_SINGLE') THEN 'SINGLE'
    WHEN v_product_code IN ('JS_DOUBLE','JP_DOUBLE','JE_DOUBLE') THEN 'DOUBLE'
    WHEN v_product_code IN ('JP_WIDE_EXP','JS_WIDE_EXP') THEN 'WIDE'
    ELSE 'DEFAULT' END);
  v_aux_model := CASE WHEN v_aux_product_code = 'JK' THEN '' ELSE COALESCE(p_model_code,'') END;

  v_material_price := calc.get_material_unit_price(p_material_code, p_quote_date);
  v_auxiliary := calc.get_auxiliary_cost(
    v_aux_product_code, v_aux_variant, v_aux_model, p_material_code,
    p_width_mm::INTEGER, p_height_mm::INTEGER, p_depth_mm::INTEGER);
  SELECT * INTO v_labor_detail
  FROM calc.get_labor_cost_with_dimension_match(
    v_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm);
  v_labor := v_labor_detail.labor_cost;
  v_weight := calc.get_corrected_material_weight_kg(
    v_product_code, p_model_code, p_material_code,
    p_width_mm, p_height_mm, p_depth_mm, p_base_material_weight_kg);
  v_spray := calc.get_product_spray_cost(
    v_product_code, COALESCE(p_model_code,''), p_material_code,
    p_width_mm, p_height_mm, p_depth_mm,
    p_product_area_m2, calc.get_spray_unit_price(p_quote_date, p_coating_type));
  v_attachment := calc.get_attachment_fee(p_quote_id, v_product_code);

  IF v_material_price IS NULL THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','material_price_missing','severity','blocker','message','材料单价缺失'));
  END IF;
  IF v_auxiliary IS NULL THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','auxiliary_price_missing','severity','warning','message','辅材价格缺失，当前按0计'));
  END IF;
  IF v_labor IS NULL THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','labor_price_missing','severity','blocker','message','人工经验值缺失'));
  ELSIF v_labor_detail.match_method <> 'exact' THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','labor_dimension_match','severity','warning',
      'message','人工费用来自同类型最近尺寸匹配，需人工确认',
      'matched_width_mm',v_labor_detail.matched_width_mm,
      'matched_height_mm',v_labor_detail.matched_height_mm,
      'matched_depth_mm',v_labor_detail.matched_depth_mm,
      'perimeter_ratio',v_labor_detail.perimeter_ratio,
      'dimension_distance',v_labor_detail.dimension_distance));
  END IF;
  IF v_is_experience AND v_spray IS NULL THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','experience_spray_missing','severity','blocker','message','经验产品直接喷塑价格待维护，不能按有效零费用报价'));
  END IF;
  SELECT COUNT(*) INTO v_unpriced_attachment_count
  FROM calc.v_attachment_selection_cost s
  WHERE s.quote_id = p_quote_id AND s.line_cost IS NULL;
  IF v_unpriced_attachment_count > 0 THEN
    v_risks := v_risks || jsonb_build_array(jsonb_build_object(
      'code','attachment_price_text','severity','blocker',
      'message',format('%s条附件价格为非数字，待确认',v_unpriced_attachment_count)));
  END IF;

  SELECT * INTO v_result
  FROM calc.calculate_quote_total(
    p_quote_id, v_product_code, COALESCE(p_model_code,''), p_material_code,
    p_width_mm, p_height_mm, p_depth_mm, p_base_material_weight_kg,
    p_product_area_m2, p_coating_type, v_aux_variant, p_quote_date);

  INSERT INTO calc.quote_request(
    quote_id,status,product_code,model_code,variant_code,material_code,
    width_mm,height_mm,depth_mm,base_material_weight_kg,product_area_m2,
    coating_type,quote_date,risk_flags,created_by,updated_at,calculated_at)
  VALUES(
    p_quote_id,'calculated',v_product_code,p_model_code,v_aux_variant,p_material_code,
    p_width_mm,p_height_mm,p_depth_mm,p_base_material_weight_kg,p_product_area_m2,
    p_coating_type,p_quote_date,v_risks,p_created_by,now(),now())
  ON CONFLICT (quote_id) DO UPDATE SET
    status='calculated', product_code=EXCLUDED.product_code,
    model_code=EXCLUDED.model_code, variant_code=EXCLUDED.variant_code,
    material_code=EXCLUDED.material_code, width_mm=EXCLUDED.width_mm,
    height_mm=EXCLUDED.height_mm, depth_mm=EXCLUDED.depth_mm,
    base_material_weight_kg=EXCLUDED.base_material_weight_kg,
    product_area_m2=EXCLUDED.product_area_m2, coating_type=EXCLUDED.coating_type,
    quote_date=EXCLUDED.quote_date, risk_flags=EXCLUDED.risk_flags,
    updated_at=now(), calculated_at=now();

  INSERT INTO calc.calculation_result(
    workflow_quote_id,workflow_status,product_code,model_code,material_code,
    corrected_material_weight_kg,material_unit_price,material_cost,
    auxiliary_cost,labor_cost,product_area_m2,spray_unit_price,spray_cost,
    attachment_fee,management_fee,total_cost,input_width_mm,input_height_mm,
    input_depth_mm,coating_type,quote_date,risk_flags,calculated_at)
  VALUES(
    p_quote_id,'calculated',v_result.product_code,v_result.model_code,v_result.material_code,
    v_result.corrected_material_weight_kg,v_result.material_unit_price,v_result.material_cost,
    v_result.auxiliary_cost,v_result.labor_cost,v_result.product_area_m2,
    v_result.spray_unit_price,v_result.spray_cost,v_result.attachment_fee,
    v_result.management_fee,v_result.total_cost,p_width_mm,p_height_mm,p_depth_mm,
    p_coating_type,p_quote_date,v_risks,now());

  RETURN QUERY SELECT
    p_quote_id,'calculated'::VARCHAR,v_result.product_code,v_result.model_code,
    v_result.material_code,v_result.corrected_material_weight_kg,v_result.material_cost,
    v_result.auxiliary_cost,v_result.labor_cost,v_result.attachment_fee,
    v_result.product_area_m2,v_result.spray_cost,v_result.management_fee,
    v_result.total_cost,v_risks;
END;
$function$;

CREATE OR REPLACE FUNCTION calc.recalculate_quote(p_quote_id VARCHAR)
RETURNS SETOF calc.quote_request
LANGUAGE plpgsql VOLATILE AS $function$
DECLARE q calc.quote_request;
BEGIN
  SELECT * INTO q FROM calc.quote_request WHERE quote_id = p_quote_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'quote not found: %', p_quote_id; END IF;
  IF q.status = 'approved' THEN RAISE EXCEPTION 'approved quote cannot be recalculated'; END IF;
  PERFORM * FROM calc.calculate_quote_api(
    q.quote_id,q.product_code,q.model_code,q.variant_code,q.width_mm,q.height_mm,
    q.depth_mm,q.material_code,q.base_material_weight_kg,q.product_area_m2,
    q.coating_type,q.quote_date,q.created_by);
  RETURN QUERY SELECT * FROM calc.quote_request WHERE quote_id = p_quote_id;
END;
$function$;

CREATE OR REPLACE FUNCTION calc.add_quote_attachment_and_recalculate(
  p_quote_id VARCHAR,
  p_product_code VARCHAR,
  p_model_code VARCHAR DEFAULT NULL,
  p_item_name VARCHAR DEFAULT NULL,
  p_quantity NUMERIC DEFAULT 1,
  p_width_mm INTEGER DEFAULT NULL,
  p_height_mm INTEGER DEFAULT NULL,
  p_depth_mm INTEGER DEFAULT NULL,
  p_variant VARCHAR DEFAULT NULL,
  p_price_source VARCHAR DEFAULT NULL,
  p_unit_price_override NUMERIC DEFAULT NULL,
  p_notes TEXT DEFAULT NULL
)
RETURNS TABLE(selection_id BIGINT, quote_status VARCHAR, attachment_fee NUMERIC, total_cost NUMERIC)
LANGUAGE plpgsql VOLATILE AS $function$
DECLARE v_selection_id BIGINT; v_quote calc.quote_request%ROWTYPE; v_total RECORD;
BEGIN
  v_selection_id := calc.add_attachment_selection(
    p_quote_id,p_product_code,p_model_code,p_item_name,p_quantity,
    p_width_mm,p_height_mm,p_depth_mm,p_variant,p_price_source,
    p_unit_price_override,p_notes);
  SELECT * INTO v_quote FROM calc.quote_request WHERE quote_id=p_quote_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'quote must be calculated before selecting attachment: %',p_quote_id; END IF;
  SELECT * INTO v_total FROM calc.calculate_quote_api(
    v_quote.quote_id,v_quote.product_code,v_quote.model_code,v_quote.variant_code,
    v_quote.width_mm,v_quote.height_mm,v_quote.depth_mm,v_quote.material_code,
    v_quote.base_material_weight_kg,v_quote.product_area_m2,v_quote.coating_type,
    v_quote.quote_date,v_quote.created_by);
  RETURN QUERY SELECT v_selection_id,p_quote_id,
    calc.get_attachment_fee(p_quote_id,v_quote.product_code),v_total.total_cost;
END;
$function$;

CREATE OR REPLACE FUNCTION calc.confirm_quote(p_quote_id VARCHAR, p_user VARCHAR DEFAULT NULL)
RETURNS VARCHAR LANGUAGE plpgsql VOLATILE AS $function$
DECLARE v_status VARCHAR;
BEGIN
  SELECT status INTO v_status FROM calc.quote_request WHERE quote_id=p_quote_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'quote not found: %',p_quote_id; END IF;
  IF v_status <> 'calculated' THEN RAISE EXCEPTION 'quote must be calculated before confirmation'; END IF;
  UPDATE calc.quote_request SET status='confirmed', confirmed_by=p_user, confirmed_at=now(), updated_at=now() WHERE quote_id=p_quote_id;
  RETURN 'confirmed';
END;
$function$;

CREATE OR REPLACE FUNCTION calc.submit_quote(p_quote_id VARCHAR, p_user VARCHAR DEFAULT NULL)
RETURNS VARCHAR LANGUAGE plpgsql VOLATILE AS $function$
DECLARE v_status VARCHAR;
BEGIN
  SELECT status INTO v_status FROM calc.quote_request WHERE quote_id=p_quote_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'quote not found: %',p_quote_id; END IF;
  IF v_status <> 'confirmed' THEN RAISE EXCEPTION 'quote must be confirmed before submission'; END IF;
  UPDATE calc.quote_request SET status='submitted', submitted_by=p_user, submitted_at=now(), updated_at=now() WHERE quote_id=p_quote_id;
  RETURN 'submitted';
END;
$function$;

CREATE OR REPLACE FUNCTION calc.approve_quote(p_quote_id VARCHAR, p_user VARCHAR DEFAULT NULL)
RETURNS VARCHAR LANGUAGE plpgsql VOLATILE AS $function$
DECLARE v_status VARCHAR;
BEGIN
  SELECT status INTO v_status FROM calc.quote_request WHERE quote_id=p_quote_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'quote not found: %',p_quote_id; END IF;
  IF v_status <> 'submitted' THEN RAISE EXCEPTION 'quote must be submitted before approval'; END IF;
  UPDATE calc.quote_request SET status='approved', approved_by=p_user, approved_at=now(), updated_at=now() WHERE quote_id=p_quote_id;
  RETURN 'approved';
END;
$function$;

COMMENT ON FUNCTION calc.calculate_quote_api IS
'Phase 2 API contract: backend passes inputs; database calls calculate_quote_total and returns costs plus risk_flags.';
COMMENT ON TABLE calc.quote_request IS
'Phase 2 quote lifecycle: draft -> calculated -> confirmed -> submitted -> approved.';

COMMIT;
