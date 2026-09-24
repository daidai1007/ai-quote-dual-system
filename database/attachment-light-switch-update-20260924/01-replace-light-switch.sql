BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';

CREATE TEMP TABLE light_switch_input(
  item_name text NOT NULL, model_code text,
  formula_cost numeric NOT NULL CHECK(formula_cost>=0),
  quick_price numeric NOT NULL CHECK(quick_price>=0),
  unit text NOT NULL, source_row_no integer PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO light_switch_input(item_name,model_code,formula_cost,quick_price,unit,source_row_no) VALUES
  ('行程开关',NULL,19.06,25,'个',1),
  ('照明灯220V长款',NULL,8.50,25,'个',2),
  ('照明灯220V短款',NULL,7.80,25,'个',3),
  ('照明灯24V-0.28m',NULL,15.00,25,'个',4),
  ('照明灯24V-0.6m',NULL,21.00,25,'个',5);

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
      AND p.import_key LIKE 'manual-20260924-light-switch-v2-%'
  ) THEN RAISE EXCEPTION '新版照明灯/行程开关数据已存在，请勿重复执行'; END IF;
END $$;

CREATE TEMP TABLE removed_light_switch(attachment_price_id bigint PRIMARY KEY) ON COMMIT DROP;
INSERT INTO removed_light_switch
SELECT DISTINCT p.attachment_price_id
FROM calc.attachment_price p
JOIN calc.attachment_classification c USING(attachment_price_id)
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.is_active AND c.category_level1 IN ('灯开关','照明灯/行程开关');

UPDATE calc.attachment_price p
SET is_active=false,
    effective_to=COALESCE(effective_to,GREATEST(CURRENT_DATE,p.effective_from + 1)),
    updated_at=now()
FROM removed_light_switch old WHERE p.attachment_price_id=old.attachment_price_id;
DELETE FROM calc.attachment_classification c USING removed_light_switch old
WHERE c.attachment_price_id=old.attachment_price_id;

INSERT INTO calc.attachment_price(
  attachment_category,item_name,model_code,variant,material_code,width_mm,height_mm,depth_mm,
  unit,price,price_text,price_source,notes,source_file,source_sheet,source_row_no,
  effective_from,effective_to,is_active,cost_method,quick_face_price,color,data_version,import_key,source_sha256
)
SELECT '照明灯/行程开关',i.item_name,i.model_code,NULL,NULL,NULL,NULL,NULL,
  i.unit,i.quick_price,i.quick_price::text,'人工维护','快速报价表二；公式法为固定成本',
  'manual-attachment-light-switch-20260924-v2','表二',i.source_row_no,
  CURRENT_DATE,NULL,true,'fixed',i.quick_price,NULL,v.data_version,
  'manual-20260924-light-switch-v2-'||lpad(i.source_row_no::text,2,'0'),NULL
FROM light_switch_input i CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_classification(
  attachment_price_id,category_level1,category_level2,category_level3,
  classification_source,created_at,updated_at
)
SELECT p.attachment_price_id,'照明灯/行程开关',NULL,NULL,
  'manual-attachment-light-switch-20260924-v2',now(),now()
FROM calc.attachment_price p JOIN active_attachment_version v USING(data_version)
WHERE p.import_key LIKE 'manual-20260924-light-switch-v2-%';

INSERT INTO calc.attachment_cost_rule(
  data_version,import_key,category_level1,category_level2,item_name,model_code,color,unit,
  method,fixed_cost,formulas,auxiliary_list,weight_not_applicable,issues,
  source_file,source_sheet,source_row_no,raw_values,notes,model_semantics
)
SELECT v.data_version,
  'manual-20260924-light-switch-rule-v2-'||lpad(i.source_row_no::text,2,'0'),
  '照明灯/行程开关','',i.item_name,i.model_code,NULL,i.unit,
  'FIXED',i.formula_cost,'{}'::jsonb,'',true,'[]'::jsonb,
  'manual-attachment-light-switch-20260924-v2','表一',i.source_row_no,
  jsonb_build_object('一级分类','照明灯/行程开关','名称',i.item_name,'型号',COALESCE(i.model_code,''),
                     '单位',i.unit,'成本',i.formula_cost,'备注','固定成本'),
  '表一固定成本',CASE WHEN i.model_code IS NULL THEN 'DESCRIPTION' ELSE 'MODEL' END
FROM light_switch_input i CROSS JOIN active_attachment_version v;

INSERT INTO calc.attachment_cost_rule_binding(attachment_price_id,rule_id)
SELECT p.attachment_price_id,r.rule_id
FROM calc.attachment_price p
JOIN calc.attachment_cost_rule r
  ON r.data_version=p.data_version AND r.source_row_no=p.source_row_no
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.import_key LIKE 'manual-20260924-light-switch-v2-%'
  AND r.import_key LIKE 'manual-20260924-light-switch-rule-v2-%';

DO $$
DECLARE v text;
BEGIN
  SELECT data_version INTO STRICT v FROM active_attachment_version;
  IF EXISTS(
    SELECT 1 FROM calc.attachment_classification c JOIN calc.attachment_price p USING(attachment_price_id)
    WHERE p.data_version=v AND p.is_active AND c.category_level1='灯开关'
  ) THEN RAISE EXCEPTION '旧一级分类“灯开关”未删除完整'; END IF;
  IF (SELECT count(*) FROM calc.attachment_price p WHERE p.data_version=v AND p.is_active
        AND p.import_key LIKE 'manual-20260924-light-switch-v2-%')<>5
     OR (SELECT count(*) FROM calc.attachment_cost_rule r WHERE r.data_version=v
        AND r.import_key LIKE 'manual-20260924-light-switch-rule-v2-%')<>5
     OR (SELECT count(*) FROM calc.attachment_cost_rule_binding b
         JOIN calc.attachment_price p USING(attachment_price_id)
         WHERE p.data_version=v AND p.import_key LIKE 'manual-20260924-light-switch-v2-%')<>5
  THEN RAISE EXCEPTION '新版目录、成本规则或绑定数量不正确'; END IF;
END $$;

SELECT c.category_level1,p.item_name,p.model_code,p.quick_face_price,p.unit,r.method,r.fixed_cost
FROM calc.attachment_price p
JOIN calc.attachment_classification c USING(attachment_price_id)
JOIN calc.attachment_cost_rule_binding b USING(attachment_price_id)
JOIN calc.attachment_cost_rule r USING(rule_id)
JOIN active_attachment_version v ON v.data_version=p.data_version
WHERE p.is_active AND p.import_key LIKE 'manual-20260924-light-switch-v2-%'
ORDER BY p.source_row_no;
COMMIT;
