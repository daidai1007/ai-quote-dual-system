BEGIN READ ONLY;

SELECT current_database() AS database_name,current_user AS database_user;

WITH definition AS (
  SELECT pg_get_functiondef(p.oid) AS body
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='calc' AND p.proname='match_quick_quote'
    AND pg_get_function_identity_arguments(p.oid)=
      'p_product_code character varying, p_model_code character varying, p_material_code character varying, p_width_mm numeric, p_height_mm numeric, p_depth_mm numeric, p_as_of_date date'
)
SELECT count(*)=1 AS function_exists,
       bool_or(position('model_rank' in body)>0) AS currently_uses_model_rank,
       bool_or(position('width_distance' in body)>0) AS currently_uses_width_priority
FROM definition;

SELECT count(*) AS active_quick_rows
FROM calc.quick_quote_experience
WHERE is_active=TRUE
  AND effective_from<=CURRENT_DATE
  AND (effective_to IS NULL OR CURRENT_DATE<effective_to);

COMMIT;
