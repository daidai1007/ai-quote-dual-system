-- B / 2026-11-03. Additive only. Do not execute against production in this task.
-- Requires attachment V2 and its immutable snapshot guards. No catalog switch.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
DO $$ BEGIN
 IF to_regclass('calc.attachment_cost_rule') IS NULL OR to_regclass('calc.attachment_quote_line') IS NULL THEN
   RAISE EXCEPTION 'Attachment V2 migration is required first';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS calc.attachment_maintenance_revision (
 attachment_price_id bigint PRIMARY KEY REFERENCES calc.attachment_price(attachment_price_id),
 logical_id bigint NOT NULL REFERENCES calc.attachment_price(attachment_price_id),
 revision_no integer NOT NULL CHECK(revision_no>0),is_current boolean NOT NULL,
 UNIQUE(logical_id,revision_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS attachment_maintenance_current
 ON calc.attachment_maintenance_revision(logical_id) WHERE is_current;
CREATE TABLE IF NOT EXISTS calc.attachment_maintenance_audit (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id uuid NOT NULL UNIQUE,actor_user_id text NOT NULL,actor_name text NOT NULL,
 action text NOT NULL CHECK(action IN ('CREATE','EDIT','ENABLE','DISABLE')),
 logical_id bigint NOT NULL,old_attachment_price_id bigint,new_attachment_price_id bigint NOT NULL,
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 500),
 before_state jsonb,after_state jsonb NOT NULL,request_payload jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION calc.attachment_maintenance_immutable_audit()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Attachment maintenance audit is append-only'; END $$;
DROP TRIGGER IF EXISTS attachment_maintenance_audit_immutable ON calc.attachment_maintenance_audit;
CREATE TRIGGER attachment_maintenance_audit_immutable BEFORE UPDATE OR DELETE ON calc.attachment_maintenance_audit
 FOR EACH ROW EXECUTE FUNCTION calc.attachment_maintenance_immutable_audit();

-- All catalog/rule changes and their audit record commit together. Old rows,
-- rule bindings, classifications and saved selections are never overwritten.
CREATE OR REPLACE FUNCTION calc.maintain_fixed_attachment(payload jsonb,actor_id text,actor_name text)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE oldp calc.attachment_price%ROWTYPE; oldc calc.attachment_classification%ROWTYPE;
 version_row calc.attachment_catalog_version%ROWTYPE; rule_row calc.attachment_cost_rule%ROWTYPE;
 old_id bigint; new_id bigint; root_id bigint; revision integer; new_rule bigint;
 op text:=payload->>'action'; request_uuid uuid:=(payload->>'request_id')::uuid;
 reason_text text:=btrim(payload->>'reason'); saved_event calc.attachment_maintenance_audit%ROWTYPE;
 before_json jsonb; after_json jsonb; fields jsonb:=payload->'item'; costs jsonb:=payload->'cost_rules';
 selected_rule jsonb; target_active boolean; existing_meta calc.attachment_maintenance_revision%ROWTYPE;
BEGIN
 IF actor_name NOT IN ('戴晨丽','姜艳娟','翟晓峰','吕芝森') OR actor_id IS NULL OR actor_id !~ '^name-user:[a-f0-9]{64}$' THEN
   RAISE EXCEPTION '无附件维护权限';
 END IF;
 IF op IS NULL OR op NOT IN ('CREATE','EDIT','ENABLE','DISABLE') OR request_uuid IS NULL
    OR reason_text IS NULL OR length(reason_text) NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION '附件维护参数无效'; END IF;
 -- Also serializes the legacy catalog add endpoint, whose CTE takes no lock.
 LOCK TABLE calc.attachment_price IN SHARE ROW EXCLUSIVE MODE;
 SELECT * INTO saved_event FROM calc.attachment_maintenance_audit WHERE request_id=request_uuid;
 IF FOUND THEN
   IF saved_event.actor_user_id<>actor_id OR saved_event.request_payload<>payload THEN RAISE EXCEPTION '保存请求已存在，内容不一致'; END IF;
   RETURN jsonb_build_object('saved',true,'replayed',true,'attachment_price_id',saved_event.new_attachment_price_id);
 END IF;
 -- switch_attachment_catalog_v2 takes the same price-table lock before
 -- changing ACTIVE. Do not demand UPDATE rights on the version registry.
 SELECT * INTO STRICT version_row FROM calc.attachment_catalog_version WHERE status='ACTIVE';
 IF op<>'CREATE' THEN
   old_id:=(payload->>'attachment_price_id')::bigint;
   SELECT * INTO STRICT oldp FROM calc.attachment_price WHERE attachment_price_id=old_id AND data_version=version_row.data_version FOR UPDATE;
   SELECT * INTO STRICT oldc FROM calc.attachment_classification WHERE attachment_price_id=old_id;
   SELECT * INTO existing_meta FROM calc.attachment_maintenance_revision WHERE attachment_price_id=old_id;
   IF FOUND AND NOT existing_meta.is_current THEN RAISE EXCEPTION '附件已被他人修改，请刷新后重试'; END IF;
   root_id:=coalesce(existing_meta.logical_id,old_id);revision:=coalesce(existing_meta.revision_no,1)+1;
   IF NOT EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding WHERE attachment_price_id=old_id)
      OR EXISTS(SELECT 1 FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id)
         WHERE b.attachment_price_id=old_id AND (r.method<>'FIXED' OR r.issues<>'[]'::jsonb)) THEN
     RAISE EXCEPTION '第一期仅支持完整固定成本附件，公式成本及仅快速报价附件不可修改';
   END IF;
   IF op='EDIT' AND (jsonb_array_length(costs)<>(SELECT count(*) FROM calc.attachment_cost_rule_binding WHERE attachment_price_id=old_id)
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(costs) c WHERE NOT EXISTS(
        SELECT 1 FROM calc.attachment_cost_rule_binding b WHERE b.attachment_price_id=old_id AND b.rule_id=(c->>'rule_id')::bigint))) THEN
     RAISE EXCEPTION '固定成本规则已变化，请刷新后重试';
   END IF;
   before_json:=jsonb_build_object('item',to_jsonb(oldp),'classification',to_jsonb(oldc),'rules',(
     SELECT jsonb_agg(to_jsonb(r) ORDER BY r.rule_id) FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id) WHERE b.attachment_price_id=old_id));
   target_active:=CASE WHEN op='ENABLE' THEN true WHEN op='DISABLE' THEN false ELSE oldp.is_active END;
   IF op IN ('ENABLE','DISABLE') AND target_active=oldp.is_active THEN RAISE EXCEPTION '附件状态已变化，请刷新后重试'; END IF;
   IF op<>'EDIT' THEN fields:=to_jsonb(oldp)||to_jsonb(oldc)||jsonb_build_object('quick_face_price',oldp.quick_face_price); END IF;
 ELSE
   revision:=1;target_active:=true;
 END IF;
 IF fields IS NULL OR fields->>'item_name' IS NULL OR btrim(fields->>'item_name')='' OR fields->>'category_level1' IS NULL
    OR btrim(fields->>'category_level1')='' OR fields->>'unit' IS NULL OR btrim(fields->>'unit')=''
    OR (fields->>'quick_face_price')::numeric<0 OR fields->>'quick_face_price' IS NULL THEN RAISE EXCEPTION '附件基本资料无效'; END IF;
 -- Names/specifications/categories/dimensions form identity; price is not
 -- identity. A change to a duplicate cannot silently create two choices.
 IF EXISTS(SELECT 1 FROM calc.attachment_price p JOIN calc.attachment_classification c USING(attachment_price_id)
   WHERE p.data_version=version_row.data_version AND p.attachment_price_id IS DISTINCT FROM old_id
   AND NOT EXISTS(SELECT 1 FROM calc.attachment_maintenance_revision m WHERE m.attachment_price_id=p.attachment_price_id AND NOT m.is_current)
   AND p.item_name=fields->>'item_name' AND coalesce(p.model_code,'')=coalesce(fields->>'model_code','')
   AND coalesce(p.variant,'')=coalesce(fields->>'variant','') AND coalesce(p.color,'')=coalesce(fields->>'color','')
   AND p.width_mm IS NOT DISTINCT FROM (fields->>'width_mm')::integer
   AND p.height_mm IS NOT DISTINCT FROM (fields->>'height_mm')::integer
   AND p.depth_mm IS NOT DISTINCT FROM (fields->>'depth_mm')::integer
   AND c.category_level1=fields->>'category_level1' AND coalesce(c.category_level2,'')=coalesce(fields->>'category_level2','')
   AND coalesce(c.category_level3,'')=coalesce(fields->>'category_level3','')) THEN
   RAISE EXCEPTION '相同分类、名称和规格的附件已存在，请编辑已有附件';
 END IF;
 new_id:=nextval(pg_get_serial_sequence('calc.attachment_price','attachment_price_id'));
 IF new_id>2147483647 THEN RAISE EXCEPTION '附件序号超过来源行号范围'; END IF;
 root_id:=coalesce(root_id,new_id);
 IF old_id IS NOT NULL THEN
   INSERT INTO calc.attachment_maintenance_revision VALUES(old_id,root_id,revision-1,false)
     ON CONFLICT(attachment_price_id) DO UPDATE SET is_current=false;
   UPDATE calc.attachment_price SET is_active=false,updated_at=now() WHERE attachment_price_id=old_id;
 END IF;
 INSERT INTO calc.attachment_price(attachment_price_id,attachment_category,item_name,model_code,variant,color,
  width_mm,height_mm,depth_mm,price,quick_face_price,price_text,unit,price_source,notes,source_file,source_sheet,source_row_no,
  is_active,data_version,import_key,source_sha256,material_code,cost_method)
 VALUES(new_id,fields->>'category_level1',fields->>'item_name',nullif(fields->>'model_code',''),nullif(fields->>'variant',''),
  nullif(fields->>'color',''),(fields->>'width_mm')::integer,(fields->>'height_mm')::integer,(fields->>'depth_mm')::integer,
  (fields->>'quick_face_price')::numeric,(fields->>'quick_face_price')::numeric,fields->>'quick_face_price',fields->>'unit',
  '软件维护',nullif(fields->>'notes',''),'attachment-maintenance','software',new_id::integer,target_active,version_row.data_version,
  'maintenance:'||new_id,version_row.source_sha256,oldp.material_code,coalesce(oldp.cost_method,'experience'));
 INSERT INTO calc.attachment_classification(attachment_price_id,category_level1,category_level2,category_level3,classification_source)
 VALUES(new_id,fields->>'category_level1',nullif(fields->>'category_level2',''),nullif(fields->>'category_level3',''),'software-maintenance');
 INSERT INTO calc.attachment_maintenance_revision VALUES(new_id,root_id,revision,true);
 IF old_id IS NULL THEN
   IF jsonb_array_length(costs)<>1 OR (costs->0->>'fixed_cost') IS NULL OR (costs->0->>'fixed_cost')::numeric<0 THEN RAISE EXCEPTION '新增附件需要一个有效固定成本'; END IF;
   INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,category_level2,item_name,model_code,unit,method,fixed_cost,
     source_file,source_sheet,source_row_no,raw_values)
   VALUES(version_row.data_version,'maintenance:'||new_id,fields->>'category_level1',coalesce(fields->>'category_level2',''),
     fields->>'item_name',nullif(fields->>'model_code',''),fields->>'unit','FIXED',(costs->0->>'fixed_cost')::numeric,
     'attachment-maintenance','software',new_id::integer,payload) RETURNING rule_id INTO new_rule;
   INSERT INTO calc.attachment_cost_rule_binding VALUES(new_id,new_rule);
   INSERT INTO calc.attachment_cost_rule_product SELECT new_rule,value FROM jsonb_array_elements_text(payload->'products');
 ELSE
   FOR rule_row IN SELECT r.* FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id) WHERE b.attachment_price_id=old_id ORDER BY r.rule_id LOOP
     selected_rule:=NULL;
     IF op='EDIT' THEN SELECT c INTO selected_rule FROM jsonb_array_elements(costs) c WHERE (c->>'rule_id')::bigint=rule_row.rule_id;
       IF (selected_rule->>'fixed_cost') IS NULL OR (selected_rule->>'fixed_cost')::numeric<0 THEN RAISE EXCEPTION '固定成本无效'; END IF;
     END IF;
     INSERT INTO calc.attachment_cost_rule(data_version,import_key,category_level1,category_level2,item_name,model_code,color,unit,method,
       fixed_cost,formulas,auxiliary_list,weight_not_applicable,issues,source_file,source_sheet,source_row_no,raw_values,notes,model_semantics)
     VALUES(version_row.data_version,'maintenance:'||new_id||':'||rule_row.rule_id,fields->>'category_level1',coalesce(fields->>'category_level2',''),
       fields->>'item_name',rule_row.model_code,rule_row.color,fields->>'unit','FIXED',
       CASE WHEN op='EDIT' THEN (selected_rule->>'fixed_cost')::numeric ELSE rule_row.fixed_cost END,
       rule_row.formulas,rule_row.auxiliary_list,rule_row.weight_not_applicable,rule_row.issues,'attachment-maintenance','software',
       new_id::integer,rule_row.raw_values,rule_row.notes,rule_row.model_semantics) RETURNING rule_id INTO new_rule;
     INSERT INTO calc.attachment_cost_rule_binding VALUES(new_id,new_rule);
     INSERT INTO calc.attachment_cost_rule_product SELECT new_rule,product_code FROM calc.attachment_cost_rule_product WHERE rule_id=rule_row.rule_id;
     INSERT INTO calc.attachment_cost_rule_material SELECT new_rule,material_code FROM calc.attachment_cost_rule_material WHERE rule_id=rule_row.rule_id;
   END LOOP;
 END IF;
 after_json:=jsonb_build_object('item',(SELECT to_jsonb(p) FROM calc.attachment_price p WHERE attachment_price_id=new_id),
  'classification',(SELECT to_jsonb(c) FROM calc.attachment_classification c WHERE attachment_price_id=new_id),
  'rules',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.rule_id) FROM calc.attachment_cost_rule_binding b JOIN calc.attachment_cost_rule r USING(rule_id) WHERE b.attachment_price_id=new_id));
 INSERT INTO calc.attachment_maintenance_audit(request_id,actor_user_id,actor_name,action,logical_id,old_attachment_price_id,new_attachment_price_id,reason,before_state,after_state,request_payload)
 VALUES(request_uuid,actor_id,actor_name,op,root_id,old_id,new_id,reason_text,before_json,after_json,payload);
 RETURN jsonb_build_object('saved',true,'attachment_price_id',new_id,'previous_attachment_price_id',old_id,'revision',revision,'data_version',version_row.data_version);
END $$;
REVOKE ALL ON FUNCTION calc.maintain_fixed_attachment(jsonb,text,text) FROM PUBLIC;
COMMENT ON FUNCTION calc.maintain_fixed_attachment(jsonb,text,text) IS 'API-authorized fixed attachment maintenance; append revisions, preserve all original snapshots.';
COMMIT;
