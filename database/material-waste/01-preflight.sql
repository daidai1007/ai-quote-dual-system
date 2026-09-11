-- Neon SQL Editor: run the whole file; read-only; no backslash commands.
-- Inspect actual online definitions BEFORE adding any multiplier.
BEGIN READ ONLY;
SELECT jsonb_pretty(jsonb_build_object(
  'database',current_database(), 'role',current_user, 'server',version(),
  'columns',(SELECT jsonb_agg(to_jsonb(c)) FROM information_schema.columns c
    WHERE table_schema='calc' AND table_name IN (
      'cabinet_template','cabinet_part_rule','experience_product_model',
      'material','attachment_cost_rule','attachment_selection')),
  'functions',(SELECT jsonb_agg(jsonb_build_object(
    'signature',p.oid::regprocedure::text,'definition',pg_get_functiondef(p.oid)))
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='calc' AND p.prokind='f' AND (
      p.proname IN ('calculate_quote_total','calculate_dual_quote',
        'calculate_total_cost_by_spray_cost','calculate_total_cost_for_quote',
        'get_corrected_material_weight_kg','get_experience_material_weight_by_dimension')
      OR p.prosrc ILIKE '%waste%' OR p.prosrc ILIKE '%scrap%'
      OR p.prosrc LIKE '%废料%' OR p.prosrc LIKE '%损耗%')),
  'coefficient_columns',(SELECT jsonb_agg(to_jsonb(c)) FROM information_schema.columns c
    WHERE table_schema='calc' AND (column_name ILIKE '%waste%' OR column_name ILIKE '%scrap%'
      OR column_name ILIKE '%loss%'))
)) AS weight_preflight;
-- Template source formulas, not quotation/customer history. A literal 1.2 may
-- also be a thickness; it is evidence to inspect, never an automatic rewrite.
SELECT jsonb_pretty(coalesce(jsonb_agg(jsonb_build_object(
  'template_id',to_jsonb(r)->'template_id',
  'template_code',to_jsonb(r)->'template_code',
  'part_rule_id',to_jsonb(r)->'part_rule_id',
  'source_sheet',to_jsonb(r)->'source_sheet',
  'source_row_no',to_jsonb(r)->'source_row_no',
  'include_material_cost',to_jsonb(r)->'include_material_cost',
  'weight_formula',to_jsonb(r)->'weight_formula',
  'raw_rule',to_jsonb(r)->'raw_rule'
)),'[]'::jsonb)) AS template_weight_rules FROM calc.cabinet_part_rule r;
COMMIT;
