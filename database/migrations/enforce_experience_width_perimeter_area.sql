-- Task B, 2026-10-28: reference selection only; existing price formulas stay intact.
-- Apply with the matching API changes. Never execute against production from tests.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

-- Refuse to replace an unrelated or subsequently customized same-name helper.
DO $rank_guard$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure('calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)')
        AND NOT (md5(p.prosrc)='d56ee2d8703d1a8ad921ff173de409e7'
          AND l.lanname='sql' AND p.provolatile='i' AND p.proisstrict
          AND p.proparallel='s' AND NOT p.prosecdef AND p.proconfig IS NULL
          AND p.prorettype='numeric[]'::regtype AND NOT p.proretset)) THEN
    RAISE EXCEPTION 'Unexpected experience rank helper; manual review required';
  END IF;
END;
$rank_guard$;

CREATE OR REPLACE FUNCTION calc.experience_dimension_rank(
  reference_width numeric,reference_height numeric,reference_depth numeric,
  target_width numeric,target_height numeric,target_depth numeric
) RETURNS numeric[] LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $rank$
  SELECT ARRAY[
    abs(reference_width-target_width),
    abs(reference_width+reference_height+reference_depth-target_width-target_height-target_depth),
    abs(2*(reference_width*reference_height+reference_width*reference_depth+reference_height*reference_depth)
      -2*(target_width*target_height+target_width*target_depth+target_height*target_depth))
  ];
$rank$;
COMMENT ON FUNCTION calc.experience_dimension_rank(numeric,numeric,numeric,numeric,numeric,numeric)
  IS 'Experience priority: width difference, perimeter difference, box surface area difference in mm2. Pricing unchanged.';

CREATE TABLE IF NOT EXISTS calc.experience_dimension_match_backup(
  migration_key text NOT NULL,function_identity text NOT NULL,original_definition text NOT NULL,
  patched_definition_md5 text NOT NULL,created_at timestamptz NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY(migration_key,function_identity)
);

DO $patch$
DECLARE
  item record;identity regprocedure;original text;updated text;pattern text;replacement text;
  rank_sql text;matches integer;existing_hash text;applied integer:=0;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('calc.match_quick_quote(character varying,character varying,character varying,numeric,numeric,numeric,date)',
      'quick','',true),
    ('calc.get_cabinet_material_fixed_weight(character varying,character varying,character varying,numeric,numeric,numeric)',
      'fixed','r',true),
    ('calc.get_cabinet_spray_fixed_cost(character varying,character varying,character varying,numeric,numeric,numeric)',
      'fixed','r',true),
    ('calc.get_auxiliary_cost(character varying,character varying,character varying,character varying,integer,integer,integer)',
      'fixed','r',true),
    ('calc.get_labor_cost_with_dimension_match(character varying,character varying,character varying,numeric,numeric,numeric)',
      'legacy-material','r',true),
    ('calc.get_experience_material_weight_by_dimension(character varying,character varying,numeric,numeric,numeric)',
      'legacy-material','epm',false),
    ('calc.get_direct_spray_cost(character varying,character varying,numeric,numeric,numeric)',
      'legacy','e',false)
  ) AS config(signature,kind,alias_name,required)
  LOOP
    identity:=to_regprocedure(item.signature);
    IF identity IS NULL THEN
      IF item.required THEN RAISE EXCEPTION 'Required experience matcher missing: %',item.signature;END IF;
      CONTINUE;
    END IF;
    original:=pg_get_functiondef(identity);
    SELECT patched_definition_md5 INTO existing_hash FROM calc.experience_dimension_match_backup
      WHERE migration_key='width-perimeter-area-20261028-v1' AND function_identity=item.signature;
    IF existing_hash IS NOT NULL THEN
      IF md5(original)<>existing_hash THEN
        RAISE EXCEPTION 'Matcher changed after this migration; review instead of overwriting: %',item.signature;
      END IF;
      applied:=applied+1;CONTINUE;
    END IF;
    -- Current compatibility overloads delegate to the V2 matcher; no body rewrite.
    IF item.kind<>'fixed' AND (strpos(original,'calc.get_cabinet_material_fixed_weight(')>0
       OR strpos(original,'calc.get_cabinet_spray_fixed_cost(')>0) THEN CONTINUE;END IF;
    IF strpos(original,'calc.experience_dimension_rank(')>0 THEN
      RAISE EXCEPTION 'Matcher already uses a rank function without this migration backup: %',item.signature;
    END IF;

    rank_sql:=CASE WHEN item.kind='quick' THEN
      'calc.experience_dimension_rank(reference_width_mm,reference_height_mm,reference_depth_mm,p_width_mm,p_height_mm,p_depth_mm)'
      ELSE format('calc.experience_dimension_rank(%s.width_mm,%s.height_mm,%s.depth_mm,p_width_mm,p_height_mm,p_depth_mm)',
        item.alias_name,item.alias_name,item.alias_name) END;
    IF item.kind='quick' THEN
      pattern:='ORDER[[:space:]]+BY[[:space:]]+width_distance[[:space:]]*,[[:space:]]*perimeter_distance[[:space:]]*,';
      replacement:='ORDER BY '||rank_sql||',';
    ELSIF item.kind='fixed' THEN
      -- A narrowly verified expression; preserve all surrounding filters, exact
      -- matching, residual ordering, return columns and price calculations.
      pattern:='abs\(\(r\.width_mm\+r\.height_mm\+r\.depth_mm\)-\(p_width_mm\+p_height_mm\+p_depth_mm\)\)';
      replacement:=rank_sql;
    ELSIF item.kind='legacy-material' THEN
      pattern:='ORDER[[:space:]]+BY[[:space:]]+material_rank[[:space:]]*,[[:space:]]*perimeter_distance[[:space:]]*,';
      replacement:='ORDER BY material_rank,'||rank_sql||',';
      IF original !~* pattern AND item.alias_name='r' THEN
        pattern:='ORDER[[:space:]]+BY[[:space:]]+material_rank[[:space:]]*,[[:space:]]*dimension_distance[[:space:]]*,[[:space:]]*model_rank';
        replacement:='ORDER BY material_rank,'||rank_sql||',dimension_distance,model_rank';
      END IF;
    ELSE
      pattern:='ORDER[[:space:]]+BY[[:space:]]+perimeter_distance[[:space:]]*,';
      replacement:='ORDER BY '||rank_sql||',';
    END IF;
    SELECT count(*) INTO matches FROM regexp_matches(original,pattern,'gi');
    IF matches<>1 THEN
      RAISE EXCEPTION 'Unexpected matcher body (% matches); review required: %',matches,item.signature;
    END IF;
    updated:=regexp_replace(original,pattern,replacement,'i');
    EXECUTE updated;
    INSERT INTO calc.experience_dimension_match_backup(migration_key,function_identity,original_definition,patched_definition_md5)
      VALUES('width-perimeter-area-20261028-v1',item.signature,original,md5(pg_get_functiondef(identity)));
    applied:=applied+1;
  END LOOP;
  IF applied<5 THEN RAISE EXCEPTION 'Not all five required experience matchers were patched';END IF;
END;
$patch$;
COMMIT;
