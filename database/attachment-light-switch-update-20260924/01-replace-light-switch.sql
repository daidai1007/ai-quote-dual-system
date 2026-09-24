\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

CREATE TEMP TABLE light_switch_input(
  model_code text PRIMARY KEY,
  formula_cost numeric NOT NULL CHECK(formula_cost>=0),
  quick_price numeric NOT NULL CHECK(quick_price>=0),
  source_row_no integer UNIQUE NOT NULL
) ON COMMIT DROP;

INSERT INTO light_switch_input(model_code,formula_cost,quick_price,source_row_no) VALUES
  ('220V',27.56,50,1),
  ('24V-0.28m',34.06,50,2),
  ('24V-0.6m',40.06,50,3);

CREATE TEMP TABLE active_attachment_version(data_version text PRIMARY KEY) ON COMMIT DROP;
INSERT INTO active_attachment_version
SELECT data_version FROM calc.attachment_catalog_version WHERE status='ACTIVE';

DO $$
BEGIN
  IF (SELECT count(*) FROM active_attachment_version)<>1 THEN
    RAISE EXCEPTION '必须且只能有一个活动附件目录版本';
  END IF;
  IF EXISTS(
    SELECT 1 FROM calc.attachment_price p,active_attachment_version v
    WHERE p.data_version=v.data_version
      AND p.import_key LIKE 'manual-20260924-light-switch-%'
  ) THEN
    RAISE EXCEPTION '本次照明灯/行程开关数据已存在，请先核对而不要重复执行';
  END IF;
END $$;

CREATE TEMP TABLE removed_light_switch(attachment_price_id bigint PRIMARY KEY) ON COMMIT DROP;
INSERT INTO removed_light_switch
SELECT p.attachment_price_id
FROM calc.attachment_price p
JOIN calc.attachment_classification c USING(attachment_price_id)
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE c.category_level1='灯开关';

-- 从现役附件库移除旧数据；价格主键可能已被历史报价引用，不物理删除主行。
UPDATE calc.attachment_price p
SET is_active=false,effective_to=COALESCE(effective_to,CURRENT_DATE),updated_at=now()
FROM removed_light_switch old
WHERE p.attachment_price_id=old.attachment_price_id;

DELETE FROM calc.attachment_classification c
USING removed_light_switch old
WHERE c.attachment_price_id=old.attachment_price_id;

INSERT INTO calc.attachment_price(
  attachment_category,item_name,model_code,variant,material_code,
  width_mm,height_mm,depth_mm,unit,price,price_text,price_source,notes,
  source_file,source_sheet,source_row_no,effective_from,effective_to,is_active,
  cost_method,quick_face_price,color,data_version,import_key,source_sha256
)
SELECT
  '照明灯/行程开关','照明灯/行程开关',i.model_code,NULL,NULL,
  NULL,NULL,NULL,'套',i.quick_price,i.quick_price::text,'人工维护',
  '快速报价表二；公式法为固定成本',
  'manual-attachment-light-switch-20260924','表二',i.source_row_no,
  CURRENT_DATE,NULL,true,'fixed',i.quick_price,NULL,v.data_version,
  'manual-20260924-light-switch-'||lower(replace(i.model_code,'.','-')),NULL
FROM light_switch_input i CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_classification(
  attachment_price_id,category_level1,category_level2,category_level3,
  classification_source,created_at,updated_at
)
SELECT p.attachment_price_id,'照明灯/行程开关',NULL,NULL,
       'manual-attachment-light-switch-20260924',now(),now()
FROM calc.attachment_price p JOIN active_attachment_version v USING(data_version)
WHERE p.import_key LIKE 'manual-20260924-light-switch-%';

INSERT INTO calc.attachment_cost_rule(
  data_version,import_key,category_level1,category_level2,item_name,model_code,color,unit,
  method,fixed_cost,formulas,auxiliary_list,weight_not_applicable,issues,
  source_file,source_sheet,source_row_no,raw_values,notes,model_semantics
)
SELECT
  v.data_version,'manual-20260924-light-switch-rule-'||lower(replace(i.model_code,'.','-')),
  '照明灯/行程开关','','照明灯/行程开关',i.model_code,NULL,'套',
  'FIXED',i.formula_cost,'{}'::jsonb,'',true,'[]'::jsonb,
  'manual-attachment-light-switch-20260924','表一',i.source_row_no,
  jsonb_build_object('一级分类','照明灯/行程开关','名称','照明灯/行程开关','型号',i.model_code,
                     '单位','套','成本',i.formula_cost,'备注','固定成本'),
  '表一固定成本','MODEL'
FROM light_switch_input i CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_cost_rule_binding(attachment_price_id,rule_id)
SELECT p.attachment_price_id,r.rule_id
FROM calc.attachment_price p
JOIN calc.attachment_cost_rule r
  ON r.data_version=p.data_version
 AND r.model_code=p.model_code
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.import_key LIKE 'manual-20260924-light-switch-%'
  AND r.import_key LIKE 'manual-20260924-light-switch-rule-%';

DO $$
DECLARE v text;
BEGIN
  SELECT data_version INTO STRICT v FROM active_attachment_version;
  IF EXISTS(
    SELECT 1 FROM calc.attachment_classification c
    JOIN calc.attachment_price p USING(attachment_price_id)
    WHERE p.data_version=v AND c.category_level1='灯开关'
  ) THEN RAISE EXCEPTION '旧一级分类“灯开关”未删除完整'; END IF;
  IF (SELECT count(*) FROM calc.attachment_price p
      WHERE p.data_version=v AND p.is_active
        AND p.import_key LIKE 'manual-20260924-light-switch-%')<>3
     OR (SELECT count(*) FROM calc.attachment_cost_rule r
         WHERE r.data_version=v
           AND r.import_key LIKE 'manual-20260924-light-switch-rule-%')<>3
     OR (SELECT count(*) FROM calc.attachment_cost_rule_binding b
         JOIN calc.attachment_price p USING(attachment_price_id)
         WHERE p.data_version=v
           AND p.import_key LIKE 'manual-20260924-light-switch-%')<>3 THEN
    RAISE EXCEPTION '新照明灯/行程开关目录、成本规则或绑定数量不正确';
  END IF;
END $$;

SELECT c.category_level1,p.item_name,p.model_code,p.quick_face_price,p.unit,
       r.method,r.fixed_cost,r.notes
FROM calc.attachment_price p
JOIN calc.attachment_classification c USING(attachment_price_id)
JOIN calc.attachment_cost_rule_binding b USING(attachment_price_id)
JOIN calc.attachment_cost_rule r USING(rule_id)
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.is_active AND p.import_key LIKE 'manual-20260924-light-switch-%'
ORDER BY p.source_row_no;

COMMIT;
