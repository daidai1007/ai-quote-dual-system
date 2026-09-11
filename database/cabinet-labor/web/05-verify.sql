BEGIN READ ONLY;
SELECT v.data_version,v.status,count(r.rule_id) AS rules
FROM calc.cabinet_labor_catalog_version v LEFT JOIN calc.cabinet_labor_rule r USING(data_version)
GROUP BY v.data_version,v.status ORDER BY v.created_at;
SELECT count(*) FILTER(WHERE status='ACTIVE') AS active_versions FROM calc.cabinet_labor_catalog_version;
COMMIT;
