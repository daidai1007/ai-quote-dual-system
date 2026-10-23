-- Read-only structural checks. No ownership assignment or privilege changes.
SELECT to_regclass('calc.quote_name_owner') IS NOT NULL AS owner_table_exists,
       to_regclass('calc.quote_name_workspace') IS NOT NULL AS personal_workspace_table_exists;
SELECT resource_kind,mapping_source,count(*) AS rows
FROM calc.quote_name_owner GROUP BY resource_kind,mapping_source ORDER BY 1,2;
SELECT count(*) AS personal_workspace_rows FROM calc.quote_name_workspace;
-- The deployment operator must separately verify the actual API database role
-- has SELECT/INSERT/UPDATE on exactly these new tables. Do not test only the
-- administrator executing this script and assume that proves API privileges.
