\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE OR REPLACE FUNCTION calc.stage_attachment_catalog_v2(bundle jsonb)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE v text:=bundle->>'data_version'; q jsonb; r jsonb; p jsonb; material text; price_id bigint; new_rule_id bigint; legacy_scale integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.attachment_catalog_v2'));
  IF v IS NULL OR length(v)=0 OR bundle->>'source_sha256' IS NULL THEN RAISE EXCEPTION 'Missing import provenance'; END IF;
  IF jsonb_typeof(bundle->'report'->'issues') IS DISTINCT FROM 'array'
     OR jsonb_array_length(bundle->'report'->'issues')<>0
     OR jsonb_typeof(bundle->'report'->'unmapped_rules') IS DISTINCT FROM 'array'
     OR jsonb_array_length(bundle->'report'->'unmapped_rules')<>0 THEN
    RAISE EXCEPTION '附件源数据存在待确认/未映射问题；禁止正式导入：%',bundle->'report'->'issues';
  END IF;
  IF jsonb_typeof(bundle->'catalog') IS DISTINCT FROM 'array' OR jsonb_array_length(bundle->'catalog')=0
    OR jsonb_typeof(bundle->'rules') IS DISTINCT FROM 'array' OR jsonb_typeof(bundle->'bindings') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Invalid import arrays'; END IF;
  IF (bundle#>>'{report,counts,quick}')::integer IS DISTINCT FROM jsonb_array_length(bundle->'catalog')
    OR (bundle#>>'{report,counts,rules}')::integer IS DISTINCT FROM jsonb_array_length(bundle->'rules')
    OR (bundle#>>'{report,counts,bindings}')::integer IS DISTINCT FROM jsonb_array_length(bundle->'bindings') THEN RAISE EXCEPTION 'Import counts differ from audit report'; END IF;
  IF EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE data_version=v) THEN RAISE EXCEPTION 'Version already staged; inspect instead of duplicating: %',v; END IF;
  SELECT numeric_scale INTO legacy_scale FROM information_schema.columns
  WHERE table_schema='calc' AND table_name='attachment_price' AND column_name='price' AND data_type='numeric';
  IF NOT FOUND THEN RAISE EXCEPTION 'Legacy price column must be numeric; inspect target schema'; END IF;
  INSERT INTO calc.attachment_catalog_version(data_version,source_sha256,status,source_file,audit_report)
  VALUES(v,bundle->>'source_sha256','STAGED',bundle->'catalog'->0->>'source_file',bundle->'report');
  FOR q IN SELECT value FROM jsonb_array_elements(bundle->'catalog') LOOP
    IF jsonb_typeof(q->'price') IS DISTINCT FROM 'number' OR (q->>'price')::numeric<0
      OR q->>'data_version' IS DISTINCT FROM v OR nullif(q->>'import_key','') IS NULL THEN RAISE EXCEPTION 'Invalid quick price/source: %',q; END IF;
    INSERT INTO calc.attachment_price(attachment_category,item_name,model_code,variant,width_mm,height_mm,depth_mm,
      price,quick_face_price,price_text,unit,price_source,source_file,source_sheet,source_row_no,is_active,color,data_version,import_key,source_sha256,notes)
    VALUES(q->>'category_level1',q->>'item_name',nullif(q->>'model_code',''),NULL,(q->>'width_mm')::integer,(q->>'height_mm')::integer,(q->>'depth_mm')::integer,
      CASE WHEN legacy_scale IS NULL THEN (q->>'price')::numeric ELSE round((q->>'price')::numeric,legacy_scale) END,
      (q->>'price')::numeric,q->>'price',nullif(q->>'unit',''),'Excel',q->>'source_file',q->>'source_sheet',(q->>'source_row_no')::integer,false,q->>'color',v,q->>'import_key',bundle->>'source_sha256',
      'V2面价见quick_face_price；price为明确舍入的旧字段兼容投影，禁止V2计算使用') RETURNING attachment_price_id INTO price_id;
    INSERT INTO calc.attachment_classification(attachment_price_id,category_level1,category_level2,category_level3,classification_source)
    VALUES(price_id,q->>'category_level1',nullif(q->>'category_level2',''),NULL,v);
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(bundle->'rules') LOOP
    IF r->>'data_version' IS DISTINCT FROM v OR jsonb_typeof(r->'issues') IS DISTINCT FROM 'array' OR jsonb_array_length(r->'issues')>0 THEN RAISE EXCEPTION 'Unresolved rule: %',r->>'import_key'; END IF;
    INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,category_level2,item_name,model_code,color,unit,
      method,fixed_cost,formulas,auxiliary_list,weight_not_applicable,issues,source_file,source_sheet,source_row_no,raw_values,notes)
    VALUES(v,r->>'import_key',r->>'category_level1',r->>'category_level2',r->>'item_name',r->>'model_code',r->>'color',r->>'unit',
      r->>'method',(r->>'fixed_cost')::numeric,r->'formulas',r->>'auxiliary_list',coalesce((r->>'weight_not_applicable')::boolean,false),r->'issues',r->>'source_file',r->>'source_sheet',(r->>'source_row_no')::integer,r->'raw_values',r->>'notes')
    RETURNING rule_id INTO new_rule_id;
    UPDATE calc.attachment_cost_rule SET model_semantics=coalesce(r->>'model_semantics','MODEL') WHERE rule_id=new_rule_id;
    INSERT INTO calc.attachment_cost_rule_product(rule_id,product_code) SELECT new_rule_id,value FROM jsonb_array_elements_text(r->'products');
    IF jsonb_typeof(r->'materials') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Missing material applicability array'; END IF;
    INSERT INTO calc.attachment_cost_rule_material(rule_id,material_code) SELECT new_rule_id,value FROM jsonb_array_elements_text(r->'materials');
    FOR p IN SELECT value FROM jsonb_array_elements(r->'parameters') LOOP
      INSERT INTO calc.attachment_cost_rule_parameter(rule_id,name,source,unit,required)
      VALUES(new_rule_id,p->>'name',p->>'source',p->>'unit',(p->>'required')::boolean);
    END LOOP;
  END LOOP;
  INSERT INTO calc.attachment_cost_rule_binding(attachment_price_id,rule_id)
  SELECT ap.attachment_price_id,cr.rule_id FROM jsonb_array_elements(bundle->'bindings') b
  JOIN calc.attachment_price ap ON ap.data_version=v AND ap.import_key=b->>'attachment_key'
  JOIN calc.attachment_cost_rule cr ON cr.data_version=v AND cr.import_key=b->>'rule_key';
  IF (SELECT count(*) FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_price ap USING(attachment_price_id) WHERE ap.data_version=v)<>jsonb_array_length(bundle->'bindings') THEN RAISE EXCEPTION 'Invalid or missing binding keys'; END IF;
  IF EXISTS(SELECT 1 FROM calc.attachment_cost_rule r WHERE r.data_version=v AND NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding b WHERE b.rule_id=r.rule_id)) THEN RAISE EXCEPTION 'Unmapped cost rules'; END IF;
  -- No automatic name-only fallback, including null/blank secondary classifications.
  IF EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_price ap USING(attachment_price_id)
    JOIN calc.attachment_classification c USING(attachment_price_id) JOIN calc.attachment_cost_rule r USING(rule_id)
    WHERE ap.data_version=v AND (r.data_version<>v OR r.category_level1 IS DISTINCT FROM c.category_level1 OR r.category_level2 IS DISTINCT FROM coalesce(c.category_level2,'') OR r.item_name IS DISTINCT FROM ap.item_name)) THEN RAISE EXCEPTION 'Cross-classification or cross-version binding'; END IF;
  -- Check generic and every explicitly supported product separately; never LIMIT 1.
  FOR q IN SELECT to_jsonb(ap) FROM calc.attachment_price ap WHERE ap.data_version=v LOOP
    FOREACH material IN ARRAY ARRAY['SECC','SUS304','SUS316'] LOOP
      PERFORM calc.resolve_attachment_cost_rule((q->>'attachment_price_id')::bigint,'__GENERIC__',material);
      FOR p IN SELECT DISTINCT to_jsonb(product_code) FROM calc.attachment_cost_rule_product pr JOIN calc.attachment_cost_rule r USING(rule_id) WHERE r.data_version=v LOOP
        PERFORM calc.resolve_attachment_cost_rule((q->>'attachment_price_id')::bigint,p#>>'{}',material);
      END LOOP;
    END LOOP;
  END LOOP;
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION calc.switch_attachment_catalog_v2(v text)
RETURNS text LANGUAGE plpgsql AS $$ BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('calc.attachment_catalog_v2'));
  IF current_setting('calc.attachment_v2_api_ready',true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION '尚未确认API/客户端V2兼容；仅允许扩展建表，禁止切换活动目录';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE data_version=v AND status='STAGED') THEN RAISE EXCEPTION 'Expected staged version: %',v; END IF;
  -- Blocks concurrent catalog writers for this short transaction, ordinary readers continue.
  LOCK TABLE calc.attachment_price IN SHARE ROW EXCLUSIVE MODE;
  UPDATE calc.attachment_price SET is_active=false WHERE is_active AND data_version IS DISTINCT FROM v;
  UPDATE calc.attachment_catalog_version SET status='RETIRED' WHERE status='ACTIVE';
  UPDATE calc.attachment_price SET is_active=true WHERE data_version=v;
  UPDATE calc.attachment_catalog_version SET status='ACTIVE',activated_at=now() WHERE data_version=v;
  RETURN v;
END $$;
CREATE OR REPLACE FUNCTION calc.activate_attachment_catalog_v2(bundle jsonb)
RETURNS text LANGUAGE plpgsql AS $$ DECLARE v text; BEGIN
  v:=calc.stage_attachment_catalog_v2(bundle);
  RETURN calc.switch_attachment_catalog_v2(v);
END $$;
REVOKE ALL ON FUNCTION calc.stage_attachment_catalog_v2(jsonb),calc.switch_attachment_catalog_v2(text),calc.activate_attachment_catalog_v2(jsonb) FROM PUBLIC;
COMMIT;
