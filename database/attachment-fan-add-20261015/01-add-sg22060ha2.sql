BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

-- Add one generic fan catalogue row and its fixed formula-cost rule to the
-- currently active V2 attachment catalogue.  Run this whole file in the
-- online PostgreSQL SQL editor; do not split the transaction.
CREATE TEMP TABLE active_attachment_version(
  data_version text PRIMARY KEY,
  source_sha256 text
) ON COMMIT DROP;

INSERT INTO active_attachment_version(data_version,source_sha256)
SELECT data_version,source_sha256
FROM calc.attachment_catalog_version
WHERE status='ACTIVE';

DO $$
BEGIN
  IF (SELECT count(*) FROM active_attachment_version)<>1 THEN
    RAISE EXCEPTION '必须且只能有一个活动附件目录版本';
  END IF;
  IF EXISTS(
    SELECT 1
    FROM calc.attachment_price p
    JOIN active_attachment_version v ON v.data_version=p.data_version
    WHERE p.is_active
      AND p.item_name IN ('风机SG22060HA2/220V(国产)','风机SG22060HA2/220V（国产）')
  ) THEN
    RAISE EXCEPTION '风机SG22060HA2/220V（国产）已存在，请先查询后勿重复新增';
  END IF;
  IF EXISTS(
    SELECT 1
    FROM calc.attachment_price p
    JOIN active_attachment_version v ON v.data_version=p.data_version
    WHERE p.is_active
      AND p.import_key='manual-20261015-fan-sg22060ha2-v1'
  ) THEN
    RAISE EXCEPTION '本次风机新增脚本已执行，请勿重复执行';
  END IF;
END $$;

CREATE TEMP TABLE new_fan(
  item_name text NOT NULL,
  category_level2 text NOT NULL,
  quick_price numeric NOT NULL CHECK(quick_price=120),
  fixed_cost numeric NOT NULL CHECK(fixed_cost=70),
  unit text NOT NULL,
  source_row_no integer NOT NULL
) ON COMMIT DROP;

INSERT INTO new_fan(item_name,category_level2,quick_price,fixed_cost,unit,source_row_no)
SELECT '风机SG22060HA2/220V（国产）','风机SG22060HA2/220V',120,70,'个',
       COALESCE(MAX(p.source_row_no),0)+1
FROM calc.attachment_price p
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.source_file='manual-attachment-fan-20261015-v1';

INSERT INTO calc.attachment_price(
  attachment_category,item_name,model_code,variant,material_code,
  width_mm,height_mm,depth_mm,unit,price,price_text,price_source,notes,
  source_file,source_sheet,source_row_no,effective_from,effective_to,
  is_active,cost_method,quick_face_price,color,data_version,import_key,
  source_sha256
)
SELECT '风机',f.item_name,NULL,NULL,NULL,NULL,NULL,NULL,f.unit,
       f.quick_price,f.quick_price::text,'人工维护','快速报价面价120；公式法固定成本70',
       'manual-attachment-fan-20261015-v1','风机',f.source_row_no,CURRENT_DATE,NULL,
       TRUE,'fixed',f.quick_price,NULL,v.data_version,
       'manual-20261015-fan-sg22060ha2-v1',v.source_sha256
FROM new_fan f
CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_classification(
  attachment_price_id,category_level1,category_level2,category_level3,
  classification_source,created_at,updated_at
)
SELECT p.attachment_price_id,'风机',f.category_level2,NULL,
       'manual-attachment-fan-20261015-v1',now(),now()
FROM calc.attachment_price p
JOIN new_fan f ON f.item_name=p.item_name
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.import_key='manual-20261015-fan-sg22060ha2-v1';

INSERT INTO calc.attachment_cost_rule(
  data_version,import_key,category_level1,category_level2,item_name,
  model_code,color,unit,method,fixed_cost,formulas,auxiliary_list,
  weight_not_applicable,issues,source_file,source_sheet,source_row_no,
  raw_values,notes,model_semantics
)
SELECT v.data_version,'manual-20261015-fan-sg22060ha2-rule-v1','风机',
       f.category_level2,f.item_name,NULL,NULL,f.unit,'FIXED',f.fixed_cost,
       '{}'::jsonb,'',TRUE,'[]'::jsonb,'manual-attachment-fan-20261015-v1',
       '风机',f.source_row_no,
       jsonb_build_object('一级分类','风机','二级分类',f.category_level2,
                          '名称','风机SG22060HA2/220V（国产）','单位',f.unit,
                          '成本',f.fixed_cost,'报价金额',f.quick_price,
                          '备注','固定成本'),
       '人工新增风机；固定成本70；快速报价面价120','MODEL'
FROM new_fan f
CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_cost_rule_binding(attachment_price_id,rule_id)
SELECT p.attachment_price_id,r.rule_id
FROM calc.attachment_price p
JOIN calc.attachment_cost_rule r
  ON r.data_version=p.data_version
 AND r.import_key='manual-20261015-fan-sg22060ha2-rule-v1'
WHERE p.import_key='manual-20261015-fan-sg22060ha2-v1';

DO $$
DECLARE v text;
BEGIN
  SELECT data_version INTO STRICT v FROM active_attachment_version;
  IF (SELECT count(*) FROM calc.attachment_price
      WHERE data_version=v AND is_active
        AND import_key='manual-20261015-fan-sg22060ha2-v1')<>1
     OR (SELECT count(*) FROM calc.attachment_classification c
         JOIN calc.attachment_price p USING(attachment_price_id)
         WHERE p.data_version=v AND p.is_active
           AND p.import_key='manual-20261015-fan-sg22060ha2-v1')<>1
     OR (SELECT count(*) FROM calc.attachment_cost_rule
         WHERE data_version=v
           AND import_key='manual-20261015-fan-sg22060ha2-rule-v1')<>1
     OR (SELECT count(*) FROM calc.attachment_cost_rule_binding b
         JOIN calc.attachment_price p USING(attachment_price_id)
         WHERE p.data_version=v
           AND p.import_key='manual-20261015-fan-sg22060ha2-v1')<>1 THEN
    RAISE EXCEPTION '风机SG22060HA2目录、分类、成本规则或绑定数量不正确';
  END IF;
  IF EXISTS(
    SELECT 1 FROM calc.attachment_price
    WHERE data_version=v AND import_key='manual-20261015-fan-sg22060ha2-v1'
      AND (quick_face_price IS DISTINCT FROM 120 OR price IS DISTINCT FROM 120
           OR unit IS DISTINCT FROM '个' OR NOT is_active)
  ) OR EXISTS(
    SELECT 1 FROM calc.attachment_cost_rule
    WHERE data_version=v AND import_key='manual-20261015-fan-sg22060ha2-rule-v1'
      AND (method IS DISTINCT FROM 'FIXED' OR fixed_cost IS DISTINCT FROM 70)
  ) THEN
    RAISE EXCEPTION '风机SG22060HA2价格或固定成本校验失败';
  END IF;
END $$;

SELECT c.category_level1,c.category_level2,p.item_name,p.quick_face_price,
       p.price,p.unit,r.method,r.fixed_cost,p.attachment_price_id
FROM calc.attachment_price p
JOIN calc.attachment_classification c USING(attachment_price_id)
JOIN calc.attachment_cost_rule_binding b USING(attachment_price_id)
JOIN calc.attachment_cost_rule r USING(rule_id)
WHERE p.is_active AND p.import_key='manual-20261015-fan-sg22060ha2-v1';

COMMIT;
