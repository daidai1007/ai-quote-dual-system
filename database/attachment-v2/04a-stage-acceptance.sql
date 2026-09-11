-- Read-only acceptance of the approved r4 STAGED import. This does not activate it.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
DO $$
DECLARE v text := 'xlsx-7b6fcb18de6f8969-r4';
BEGIN
  IF NOT EXISTS(SELECT 1 FROM calc.attachment_catalog_version WHERE data_version=v AND status='STAGED'
    AND source_sha256='7b6fcb18de6f896942a627f70abbd91ba4e5587ed87e57abe837b4c03f043a64') THEN
    RAISE EXCEPTION 'Expected approved r4 STAGED version and source hash';
  END IF;
  IF (SELECT count(*) FROM calc.attachment_price WHERE data_version=v)<>226
    OR EXISTS(SELECT 1 FROM calc.attachment_price WHERE data_version=v AND (is_active OR quick_face_price IS NULL)) THEN
    RAISE EXCEPTION 'Expected 226 inactive rows, each with an exact face price';
  END IF;
  IF (SELECT count(*) FROM calc.attachment_classification c JOIN calc.attachment_price p USING(attachment_price_id) WHERE p.data_version=v)<>226 THEN RAISE EXCEPTION 'Expected 226 classification relations'; END IF;
  IF (SELECT count(*) FROM calc.attachment_cost_rule WHERE data_version=v AND method='FIXED')<>32
    OR (SELECT count(*) FROM calc.attachment_cost_rule WHERE data_version=v AND method='CALCULATED')<>30 THEN RAISE EXCEPTION 'Expected 32 fixed and 30 calculated rules'; END IF;
  IF (SELECT count(*) FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_price p USING(attachment_price_id) WHERE p.data_version=v)<>264 THEN RAISE EXCEPTION 'Expected 264 rule bindings'; END IF;
  IF (SELECT count(*) FROM calc.attachment_cost_rule_material m JOIN calc.attachment_cost_rule r USING(rule_id) WHERE r.data_version=v)<>9 THEN RAISE EXCEPTION 'Expected 9 material relations'; END IF;
  IF (SELECT count(*) FROM calc.attachment_price p WHERE p.data_version=v AND NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding b WHERE b.attachment_price_id=p.attachment_price_id))<>8 THEN RAISE EXCEPTION 'Expected 8 quick-only catalog rows'; END IF;
END $$;
SELECT 'PASS: r4 imported and remains STAGED; no active catalog switch' AS result;
SELECT p.source_row_no AS quick_row,m.material_code,r.fixed_cost,p.quick_face_price
FROM calc.attachment_price p
CROSS JOIN (VALUES('SECC'),('SUS304'),('SUS316')) m(material_code)
JOIN calc.attachment_cost_rule r ON r.rule_id=calc.resolve_attachment_cost_rule(p.attachment_price_id,'JP',m.material_code)
WHERE p.data_version='xlsx-7b6fcb18de6f8969-r4' AND p.source_row_no IN (103,104,105,208,226)
ORDER BY p.source_row_no,m.material_code;
COMMIT;
