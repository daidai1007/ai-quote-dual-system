BEGIN READ ONLY;
SELECT current_database(),current_user,version();
SELECT to_regclass('calc.dual_quote_result') AS dual_quote_result,
       to_regclass('calc.auxiliary_bom') AS old_auxiliary_bom,
       to_regclass('calc.auxiliary_bom_line') AS old_auxiliary_bom_line;
SELECT column_name,data_type FROM information_schema.columns
WHERE table_schema='calc' AND table_name='dual_quote_result' ORDER BY ordinal_position;
COMMIT;
