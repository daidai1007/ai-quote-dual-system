/*
  Repair JP frame quantity formulas after extend_jp_frame_formula_template.sql.

  Excel evaluates IF branches lazily.  The recovered V3 formula evaluator is
  eager, so the original rows 42-43 could divide by the default B15 = 0 even
  when the affected branch was not selected.  The replacements below are
  algebraically equivalent for every non-zero B15 and safe when B15 is zero.
*/
BEGIN;

DO $assert$
DECLARE missing_templates TEXT;
BEGIN
  SELECT string_agg(wanted.code, ', ' ORDER BY wanted.code)
    INTO missing_templates
  FROM (VALUES ('JP_SINGLE'), ('JP_DOUBLE')) AS wanted(code)
  LEFT JOIN calc.cabinet_template t ON t.template_code = wanted.code
  WHERE t.template_id IS NULL;
  IF missing_templates IS NOT NULL THEN
    RAISE EXCEPTION 'Missing JP formula templates: %', missing_templates;
  END IF;
END;
$assert$;

WITH replacement(source_row_no, safe_formula) AS (
  VALUES
    (42, '=IF(AND($B$23=1,$B$14=1,$B$25=0),$B$9-$B$15,IF(AND($B$23=1,$B$14=1,$B$25=1),2*$B$9-$B$15,$B$9*$B$23))'),
    (43, '=IF(AND($B$14=1,$B$9<>1),($B$9-$B$15)*4,)')
)
UPDATE calc.cabinet_part_rule r
SET total_quantity_formula = replacement.safe_formula,
    raw_rule = jsonb_set(
      r.raw_rule,
      '{formulas,8}',
      to_jsonb(replacement.safe_formula),
      false
    )
FROM calc.cabinet_template t
CROSS JOIN replacement
WHERE r.template_id = t.template_id
  AND t.template_code IN ('JP_SINGLE', 'JP_DOUBLE')
  AND r.source_row_no = replacement.source_row_no;

DO $verify$
DECLARE mismatch TEXT;
BEGIN
  SELECT string_agg(
           format('%s row %s', t.template_code, expected.source_row_no),
           ', '
           ORDER BY t.template_code, expected.source_row_no
         )
    INTO mismatch
  FROM calc.cabinet_template t
  CROSS JOIN (
    VALUES
      (42, '=IF(AND($B$23=1,$B$14=1,$B$25=0),$B$9-$B$15,IF(AND($B$23=1,$B$14=1,$B$25=1),2*$B$9-$B$15,$B$9*$B$23))'),
      (43, '=IF(AND($B$14=1,$B$9<>1),($B$9-$B$15)*4,)')
  ) AS expected(source_row_no, safe_formula)
  LEFT JOIN calc.cabinet_part_rule r
    ON r.template_id = t.template_id
   AND r.source_row_no = expected.source_row_no
  WHERE t.template_code IN ('JP_SINGLE', 'JP_DOUBLE')
    AND (
      r.rule_id IS NULL
      OR r.total_quantity_formula IS DISTINCT FROM expected.safe_formula
      OR r.raw_rule->'formulas'->>8 IS DISTINCT FROM expected.safe_formula
    );
  IF mismatch IS NOT NULL THEN
    RAISE EXCEPTION 'JP eager-IF formula repair mismatch: %', mismatch;
  END IF;
END;
$verify$;

COMMIT;
