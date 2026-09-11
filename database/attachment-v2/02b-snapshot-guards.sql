\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE OR REPLACE FUNCTION calc.guard_attachment_selection_v2()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ap calc.attachment_price%ROWTYPE; owner_line calc.attachment_quote_line%ROWTYPE; rule calc.attachment_cost_rule%ROWTYPE; expected_rule bigint; classification calc.attachment_classification%ROWTYPE;
BEGIN
  IF TG_OP IN ('UPDATE','DELETE') AND OLD.calculation_status IS NOT NULL THEN
    RAISE EXCEPTION 'V2附件报价快照不可覆盖或删除；请新建报价行版本';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  IF NEW.calculation_status IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO STRICT ap FROM calc.attachment_price WHERE attachment_price_id=NEW.attachment_price_id;
  SELECT * INTO STRICT classification FROM calc.attachment_classification WHERE attachment_price_id=NEW.attachment_price_id;
  SELECT * INTO STRICT owner_line FROM calc.attachment_quote_line WHERE quote_line_id=NEW.quote_line_id;
  IF NEW.quote_id IS DISTINCT FROM owner_line.quote_id OR NEW.product_code IS DISTINCT FROM owner_line.product_code
    OR NEW.environment_snapshot IS DISTINCT FROM owner_line.environment_snapshot THEN RAISE EXCEPTION '附件归属或报价环境不一致'; END IF;
  IF NEW.catalog_version IS DISTINCT FROM ap.data_version OR NEW.quick_face_price IS DISTINCT FROM ap.quick_face_price THEN RAISE EXCEPTION '附件目录版本或面价不一致'; END IF;
  IF NEW.price_sign=-1 AND (position('安装板' IN ap.item_name||' '||coalesce(ap.attachment_category,''))=0
    OR position('安装板单发' IN ap.item_name||' '||coalesce(ap.attachment_category,''))>0) THEN RAISE EXCEPTION '该附件不允许扣减'; END IF;
  IF NOT NEW.cost_snapshot ?& ARRAY['item_name','category_level1','category_level2','unit','auxiliary_list'] THEN RAISE EXCEPTION '缺少附件身份/辅材清单快照'; END IF;
  IF NEW.cost_snapshot->>'item_name' IS DISTINCT FROM ap.item_name
    OR NEW.cost_snapshot->>'category_level1' IS DISTINCT FROM classification.category_level1
    OR NEW.cost_snapshot->>'category_level2' IS DISTINCT FROM coalesce(classification.category_level2,'')
    OR NEW.cost_snapshot->>'unit' IS DISTINCT FROM coalesce(ap.unit,'') THEN RAISE EXCEPTION '附件身份或单位快照不一致'; END IF;
  IF NEW.calculation_status<>'ERROR' THEN
    expected_rule:=calc.resolve_attachment_cost_rule(NEW.attachment_price_id,NEW.product_code,owner_line.environment_snapshot->>'material_code');
    IF NEW.cost_rule_id IS DISTINCT FROM expected_rule THEN RAISE EXCEPTION '所选成本规则不是当前产品适用规则'; END IF;
    IF expected_rule IS NOT NULL THEN
      SELECT * INTO STRICT rule FROM calc.attachment_cost_rule WHERE rule_id=expected_rule;
      IF rule.issues<>'[]'::jsonb THEN RAISE EXCEPTION '成本规则仍有待确认事项'; END IF;
      IF NEW.rule_version IS DISTINCT FROM rule.data_version OR NEW.cost_snapshot->>'auxiliary_list' IS DISTINCT FROM rule.auxiliary_list THEN RAISE EXCEPTION '成本规则版本或辅材清单不一致'; END IF;
      IF NEW.calculation_status='FIXED' AND (rule.method<>'FIXED' OR NEW.formula_unit_cost IS DISTINCT FROM rule.fixed_cost) THEN RAISE EXCEPTION '固定成本不一致'; END IF;
      IF NEW.calculation_status='CALCULATED' THEN
        IF rule.method<>'CALCULATED' OR NOT NEW.cost_snapshot ?& ARRAY['weight_kg','material_cost','spray_area_m2','spray_cost','auxiliary_cost','labor_cost'] THEN RAISE EXCEPTION '缺少动态成本组成'; END IF;
        IF EXISTS(SELECT 1 FROM unnest(ARRAY['material_cost','spray_area_m2','spray_cost','auxiliary_cost','labor_cost']) k WHERE jsonb_typeof(NEW.cost_snapshot->k) IS DISTINCT FROM 'number' OR (NEW.cost_snapshot->>k)::numeric<0) THEN RAISE EXCEPTION '动态成本组成必须是非负数'; END IF;
        IF round(NEW.formula_unit_cost,8) IS DISTINCT FROM round((NEW.cost_snapshot->>'material_cost')::numeric+(NEW.cost_snapshot->>'spray_cost')::numeric+(NEW.cost_snapshot->>'auxiliary_cost')::numeric+(NEW.cost_snapshot->>'labor_cost')::numeric,8) THEN RAISE EXCEPTION '成本组成与单位成本不一致'; END IF;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS attachment_selection_v2_guard ON calc.attachment_selection;
CREATE TRIGGER attachment_selection_v2_guard BEFORE INSERT OR UPDATE OR DELETE ON calc.attachment_selection
FOR EACH ROW EXECUTE FUNCTION calc.guard_attachment_selection_v2();
CREATE OR REPLACE FUNCTION calc.guard_attachment_quote_line_v2()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION '报价行环境快照不可变；请创建新报价行ID';
END $$;
DROP TRIGGER IF EXISTS attachment_quote_line_v2_guard ON calc.attachment_quote_line;
CREATE TRIGGER attachment_quote_line_v2_guard BEFORE UPDATE OR DELETE ON calc.attachment_quote_line
FOR EACH ROW EXECUTE FUNCTION calc.guard_attachment_quote_line_v2();
COMMIT;
