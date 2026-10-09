const sqlText = value => `'${String(value).replaceAll("'", "''")}'`;

// The version covers the actual mapping, formulas and complete ordered rules,
// including in-place edits which do not change a catalog's display version.
export const formulaTemplateSql = (productCode, knownVersion = '') => `
WITH templates AS (
  SELECT m.template_code, m.source_sheet, m.width_cell, m.height_cell,
         m.depth_cell, m.option_cells, m.weight_output_cell, m.area_output_cell,
         m.weight_method, m.area_unit,
         t.weight_formula AS template_weight_formula,
         t.area_formula AS template_area_formula,
         jsonb_agg(to_jsonb(r) ORDER BY r.source_row_no, to_jsonb(r)::text) AS rules
  FROM calc.template_formula_mapping m
  JOIN calc.cabinet_template t ON t.template_code = m.template_code
  JOIN calc.cabinet_part_rule r ON r.template_id = t.template_id
  WHERE m.template_code = ${sqlText(productCode)}
    AND m.is_active = TRUE AND t.is_active = TRUE
  GROUP BY m.template_code, m.source_sheet, m.width_cell, m.height_cell,
           m.depth_cell, m.option_cells, m.weight_output_cell, m.area_output_cell,
           m.weight_method, m.area_unit, t.weight_formula, t.area_formula
), versioned AS (
  SELECT to_jsonb(t) AS template, md5(to_jsonb(t)::text) AS version FROM templates t
)
SELECT jsonb_build_object(
  'template_version', version,
  'not_modified', version = ${sqlText(knownVersion)},
  'template', CASE WHEN version = ${sqlText(knownVersion)} THEN NULL ELSE template END,
  'source', 'postgresql'
)::text FROM versioned;`;
