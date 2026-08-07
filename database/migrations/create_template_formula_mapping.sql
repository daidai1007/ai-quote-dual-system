/* Excel产品计算模板参数映射 */
CREATE TABLE IF NOT EXISTS calc.template_formula_mapping (
  mapping_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  template_code VARCHAR(30) NOT NULL UNIQUE,
  source_file VARCHAR(300) NOT NULL,
  source_sheet VARCHAR(100) NOT NULL,
  width_cell VARCHAR(20) NOT NULL DEFAULT 'B6',
  height_cell VARCHAR(20) NOT NULL DEFAULT 'B7',
  depth_cell VARCHAR(20) NOT NULL DEFAULT 'B8',
  option_cells JSONB NOT NULL DEFAULT '{}'::JSONB,
  weight_output_cell VARCHAR(20) NOT NULL,
  area_output_cell VARCHAR(20) NOT NULL,
  weight_method VARCHAR(30) NOT NULL DEFAULT 'formula_secc_base',
  area_unit VARCHAR(20) NOT NULL DEFAULT 'm2',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO calc.template_formula_mapping
  (template_code, source_file, source_sheet, option_cells,
   weight_output_cell, area_output_cell, notes)
VALUES
  ('JS_SINGLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JS单门',
   '{"count":"B9","door":"B10","lock_830":"B11","lock_828":"B12","box_thickness":"B14","mounting_plate":"B15","plate_thickness":"B16","longitudinal_beam":"B17","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_strip":"B22"}'::JSONB,
   'H28', 'N28', 'JS单门模板；H28:K28为合并单元格，读取左上角H28'),
  ('JS_DOUBLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JS双门',
   '{"count":"B9","longitudinal_beam":"B10","door":"B11","lock_830":"B12","lock_828":"B13","box_thickness":"B14","mounting_plate":"B15","plate_thickness":"B16","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_strip":"B22"}'::JSONB,
   'H28', 'N28', 'JS双门模板；H28:K28为合并单元格，读取左上角H28'),
  ('JP_SINGLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JP单门',
   '{"count":"B9","door_or_beam":"B10","lock_830":"B11","lock_828":"B12","parallel_cabinets":"B13","group_count":"B14","mounting_plate":"B15","plate_thickness":"B16","longitudinal_beam":"B17","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_strip":"B22","filler_plate":"B23"}'::JSONB,
   'H28', 'N28', 'JP单门模板；H28:K28为合并单元格，读取左上角H28'),
  ('JP_DOUBLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JP双门',
   '{"count":"B9","longitudinal_beam":"B10","door":"B11","lock_830":"B12","lock_828":"B13","parallel_cabinets":"B14","group_count":"B15","mounting_plate":"B16","plate_thickness":"B17","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_strip":"B22","filler_plate":"B23","wide_cabinet":"B24"}'::JSONB,
   'H29', 'N29', 'JP双门模板；H29:K29为合并单元格，读取左上角H29'),
  ('JA_SINGLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JA单门',
   '{"count":"B9","orientation":"B10","box_thickness":"B11","door_thickness":"B13","corner_piece":"B14","wire_tie":"B15","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_plate":"B23","plate_thickness":"B24"}'::JSONB,
   'H28', 'N28', 'JA单门模板；H28:K28为合并单元格，读取左上角H28，B10/B11参与公式计算'),
  ('JE_SINGLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JE单门',
   '{"count":"B9","orientation":"B10","box_thickness":"B11","door_thickness":"B13","corner_piece":"B14","wire_tie":"B15","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_plate":"B23","plate_thickness":"B24"}'::JSONB,
   'H28', 'N28', 'JE单门模板；H28:K28为合并单元格，读取左上角H28'),
  ('JE_DOUBLE', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JE双门',
   '{"count":"B9","orientation":"B10","box_thickness":"B11","door_thickness":"B13","corner_piece":"B14","wire_tie":"B15","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_plate":"B23","plate_thickness":"B24"}'::JSONB,
   'H28', 'N28', 'JE双门模板；H28:K28为合并单元格，读取左上角H28'),
  ('JK', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JK',
   '{"count":"B9","orientation":"B10","mounting_plate":"B12","plate_thickness":"B13"}'::JSONB,
   'H26', 'N26', 'JK模板H26:K26为合并单元格，读取左上角H26'),
  ('JM', 'G:/gongsi/banjinxitong/表格资料准备/产品计算表.xlsx', 'JM',
   '{"count":"B9","orientation":"B10","box_thickness":"B11","door_thickness":"B13","corner_piece":"B14","wire_tie":"B15","fixed_height":"B18","moving_height":"B19","thickness":"B20","base_color":"B21","mounting_plate":"B23","plate_thickness":"B24"}'::JSONB,
   'H28', 'N28', 'JM模板；H28:K28为合并单元格，读取左上角H28，B10/B11参与公式计算')
ON CONFLICT (template_code) DO UPDATE SET
  source_file = EXCLUDED.source_file,
  source_sheet = EXCLUDED.source_sheet,
  width_cell = EXCLUDED.width_cell,
  height_cell = EXCLUDED.height_cell,
  depth_cell = EXCLUDED.depth_cell,
  option_cells = EXCLUDED.option_cells,
  weight_output_cell = EXCLUDED.weight_output_cell,
  area_output_cell = EXCLUDED.area_output_cell,
  weight_method = EXCLUDED.weight_method,
  area_unit = EXCLUDED.area_unit,
  notes = EXCLUDED.notes,
  is_active = EXCLUDED.is_active;

CREATE INDEX IF NOT EXISTS idx_template_formula_mapping_active
  ON calc.template_formula_mapping(is_active, template_code);

COMMENT ON TABLE calc.template_formula_mapping
  IS 'Excel柜体计算模板的输入参数、输出单元格和计算来源映射';

SELECT template_code, source_sheet, width_cell, height_cell, depth_cell,
       weight_output_cell, area_output_cell, weight_method, area_unit
FROM calc.template_formula_mapping
ORDER BY mapping_id;
