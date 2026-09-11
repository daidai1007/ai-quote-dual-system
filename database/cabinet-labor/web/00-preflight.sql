BEGIN READ ONLY;
SELECT current_database(),current_user,version();
SELECT to_regclass('calc.dual_quote_result') AS dual_quote_result,
       to_regclass('calc.cabinet_material_rule') AS cabinet_material_rule,
       to_regclass('calc.labor_experience_rule') AS old_labor_rule;
SELECT column_name,data_type FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result'
ORDER BY ordinal_position;
COMMIT;
