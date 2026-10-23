-- Read-only candidate preview. Never auto-claim on login. Review/confirmation
-- and a separately approved allocation script are required before any INSERT.
SELECT s.scheme_id,s.scheme_no,s.creator_user_id,s.creator_name_entered,
       NULLIF(normalize(btrim(s.creator_name_entered),NFC),'') AS proposed_name,
       '原始创建姓名；待人工确认，尚未分配' AS mapping_basis
FROM calc.quote_scheme s
WHERE s.creator_user_id NOT LIKE 'name-user:%'
  AND NOT EXISTS(SELECT 1 FROM calc.quote_name_owner own WHERE own.resource_kind='SCHEME' AND own.resource_key=s.scheme_id::text)
ORDER BY s.scheme_id;

-- Imported contract-price evidence has no reliable original creator field.
-- Leave owner NULL until separately confirmed; do not infer from last editor.
SELECT source_row_no AS resource_key,NULL::text AS proposed_name,
       '导入合同价格；缺少可靠创建归属，待人工核实，仅ALL可见' AS mapping_basis
FROM calc."历史价格" h
WHERE NOT EXISTS(SELECT 1 FROM calc.quote_name_owner own WHERE own.resource_kind='HISTORY_PRICE' AND own.resource_key=h.source_row_no::text)
ORDER BY source_row_no;
