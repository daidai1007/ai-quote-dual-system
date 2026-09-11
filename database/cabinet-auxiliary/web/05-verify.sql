BEGIN READ ONLY;
SELECT v.data_version,v.status,count(DISTINCT p.profile_id) AS profiles,count(l.line_id) AS lines
FROM calc.cabinet_auxiliary_catalog_version v
LEFT JOIN calc.cabinet_auxiliary_profile p USING(data_version)
LEFT JOIN calc.cabinet_auxiliary_line l USING(profile_id)
GROUP BY v.data_version,v.status ORDER BY v.created_at;
SELECT count(*) FILTER(WHERE status='ACTIVE') AS active_versions FROM calc.cabinet_auxiliary_catalog_version;
COMMIT;
