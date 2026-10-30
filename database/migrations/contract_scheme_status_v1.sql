-- Explicit deployment only. No historical contracts are backfilled.
BEGIN;
SET LOCAL lock_timeout='5s';
DO $$
DECLARE target regclass; constraint_row record; literals text[];
BEGIN
  FOREACH target IN ARRAY ARRAY['calc.quote_scheme'::regclass,'calc.quote_scheme_version'::regclass] LOOP
    FOR constraint_row IN SELECT c.conname,c.conkey,pg_get_constraintdef(c.oid) AS definition
      FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
      WHERE c.conrelid=target AND c.contype='c' AND a.attname='status'
    LOOP
      SELECT array_agg(DISTINCT match[1] ORDER BY match[1]) INTO literals
        FROM regexp_matches(constraint_row.definition,'''([^'']+)''','g') match;
      IF literals IS NULL OR cardinality(constraint_row.conkey)<>1 THEN
        RAISE EXCEPTION 'Review custom multi-column status constraint before migration: %',constraint_row.definition;
      END IF;
      IF target='calc.quote_scheme'::regclass THEN
        IF literals NOT IN (ARRAY['ARCHIVED','DRAFT','QUOTED','REVISING','VOID'],ARRAY['ARCHIVED','CONTRACT','DRAFT','QUOTED','REVISING','VOID']) THEN
          RAISE EXCEPTION 'Unknown quote scheme status constraint: %',constraint_row.definition;
        END IF;
      ELSE
        IF literals NOT IN (ARRAY['ARCHIVED','QUOTED','VOID'],ARRAY['ARCHIVED','CONTRACT','QUOTED','VOID']) THEN
          RAISE EXCEPTION 'Unknown quote version status constraint: %',constraint_row.definition;
        END IF;
      END IF;
      EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',target,constraint_row.conname);
    END LOOP;
  END LOOP;
END $$;
ALTER TABLE calc.quote_scheme ADD CONSTRAINT quote_scheme_status_check
  CHECK(status IN ('DRAFT','QUOTED','CONTRACT','REVISING','ARCHIVED','VOID'));
ALTER TABLE calc.quote_scheme_version ADD CONSTRAINT quote_scheme_version_status_check
  CHECK(status IN ('QUOTED','CONTRACT','ARCHIVED','VOID'));
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'QUOTE'
  CHECK(source_kind IN ('QUOTE','LEDGER_CONTRACT'));
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS contracted_at timestamptz;
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS contract_amount numeric(18,2);
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS contract_record_id uuid;
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS contract_version_no integer;
ALTER TABLE calc.quote_scheme ADD COLUMN IF NOT EXISTS contract_source_kind text
  CHECK(contract_source_kind IN ('QUOTE','LEDGER'));

CREATE TABLE IF NOT EXISTS calc.quote_scheme_contract_link (
  link_id bigserial PRIMARY KEY,
  scheme_id bigint NOT NULL REFERENCES calc.quote_scheme(scheme_id),
  scheme_version_no integer NOT NULL CHECK(scheme_version_no>0),
  source_kind text NOT NULL CHECK(source_kind IN ('QUOTE','LEDGER')),
  contract_record_id uuid NOT NULL,
  contract_amount numeric(18,2) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(source_kind,contract_record_id)
);
CREATE INDEX IF NOT EXISTS idx_scheme_contract_version ON calc.quote_scheme_contract_link(scheme_id,scheme_version_no);
CREATE OR REPLACE FUNCTION calc.guard_scheme_contract_link() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'contract scheme associations are immutable'; END $$;
DROP TRIGGER IF EXISTS trg_scheme_contract_link_immutable ON calc.quote_scheme_contract_link;
CREATE TRIGGER trg_scheme_contract_link_immutable BEFORE UPDATE OR DELETE ON calc.quote_scheme_contract_link
  FOR EACH ROW EXECUTE FUNCTION calc.guard_scheme_contract_link();

CREATE OR REPLACE FUNCTION calc.register_generated_contract(p_kind text,p_record_id uuid,p_identity_mode text DEFAULT 'AUTHENTICATED')
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE r record; s calc.quote_scheme%ROWTYPE; sid bigint; payload jsonb; items jsonb;
  amount numeric; previous_status text; new_link bigint; source_version integer;
BEGIN
  SELECT scheme_id INTO sid FROM calc.quote_scheme_contract_link
    WHERE source_kind=p_kind AND contract_record_id=p_record_id;
  IF FOUND THEN
    SELECT * INTO s FROM calc.quote_scheme WHERE scheme_id=sid;
    RETURN jsonb_build_object('scheme_no',s.scheme_no,'status',s.status,'lock_version',s.lock_version,'version_no',s.version_no,'source_kind',s.source_kind,'contract_record_id',p_record_id);
  END IF;
  IF p_kind='QUOTE' THEN
    SELECT * INTO STRICT r FROM calc.contract_generation WHERE record_id=p_record_id;
    SELECT * INTO STRICT s FROM calc.quote_scheme WHERE scheme_id=r.source_scheme_id FOR UPDATE;
    sid=s.scheme_id;source_version=r.source_version_no;previous_status=s.status;
    amount=(r.generation_snapshot#>>'{quote,total}')::numeric;
  ELSIF p_kind='LEDGER' THEN
    SELECT * INTO STRICT r FROM calc.ledger_contract_generation WHERE record_id=p_record_id;
    amount=(r.generation_snapshot#>>'{quote,total}')::numeric;
    INSERT INTO calc.quote_scheme(scheme_no,status,source_kind,version_no,company_name,product_summary,quoted_amount,
      creator_user_id,creator_name_snapshot,creator_name_entered,creator_identity_mode,last_editor_user_id,last_editor_name_snapshot,
      contracted_at,contract_amount,contract_record_id,contract_version_no,contract_source_kind)
    VALUES(calc.next_quote_scheme_number(),'CONTRACT','LEDGER_CONTRACT',1,r.customer_name,
      COALESCE((SELECT string_agg(name,'；') FROM (SELECT DISTINCT value->>'name' AS name FROM jsonb_array_elements(r.generation_snapshot#>'{quote,items}')) names),''),amount,
      r.owner_user_id,r.owner_name,r.owner_name,CASE WHEN p_identity_mode='NAME_ONLY' THEN 'SELF_REPORTED' ELSE 'AUTHENTICATED' END,r.owner_user_id,r.owner_name,
      clock_timestamp(),amount,p_record_id,1,'LEDGER') RETURNING * INTO s;
    sid=s.scheme_id;source_version=1;previous_status=NULL;
    SELECT COALESCE(jsonb_agg(jsonb_build_object('name',value->>'name','quantity',value->'quantity',
      'specification',value->>'specification','quote_method','LEDGER','quote_display',value)),'[]'::jsonb)
      INTO items FROM jsonb_array_elements(r.generation_snapshot#>'{quote,items}');
    payload=jsonb_build_object('company',r.customer_name,'document',jsonb_build_object('scheme_no',s.scheme_no,'version_no',1,'order_nature','EXTERNAL','source_kind','LEDGER_CONTRACT','contract_record_id',p_record_id),
      'analysis_customer',jsonb_build_object('customer_code',r.customer_code,'customer_name',r.customer_name),
      'scheme_summary',jsonb_build_object('company',r.customer_name,'quoted_amount',amount,'product_summary',s.product_summary),
      'draft_items',items,'ledger_contract_snapshot',r.generation_snapshot);
    INSERT INTO calc.quote_scheme_snapshot(scheme_id,snapshot_payload,saved_by_user_id,saved_by_name_snapshot)
      VALUES(sid,payload,r.owner_user_id,r.owner_name);
    INSERT INTO calc.quote_scheme_version(scheme_id,version_no,status,snapshot_payload) VALUES(sid,1,'CONTRACT',payload);
    INSERT INTO calc.quote_scheme_item(scheme_id,line_no,item_payload)
      SELECT sid,ordinality::integer,value FROM jsonb_array_elements(items) WITH ORDINALITY;
  ELSE
    RAISE EXCEPTION 'Unknown contract source kind';
  END IF;
  IF amount IS NULL OR amount<0 THEN RAISE EXCEPTION 'Invalid contract amount'; END IF;
  INSERT INTO calc.quote_scheme_contract_link(scheme_id,scheme_version_no,source_kind,contract_record_id,contract_amount)
    VALUES(sid,source_version,p_kind,p_record_id,amount) ON CONFLICT(source_kind,contract_record_id) DO NOTHING RETURNING link_id INTO new_link;
  IF new_link IS NULL THEN RAISE EXCEPTION 'Contract registration raced; retry the same request'; END IF;
  -- A contract for an older frozen version must not overwrite a newer revision.
  IF p_kind='QUOTE' AND s.version_no=source_version AND s.status IN ('QUOTED','ARCHIVED','CONTRACT') THEN
    UPDATE calc.quote_scheme SET status='CONTRACT',contracted_at=clock_timestamp(),contract_amount=amount,
      contract_record_id=p_record_id,contract_version_no=source_version,contract_source_kind='QUOTE',lock_version=lock_version+1,
      updated_at=clock_timestamp(),last_editor_user_id=r.owner_user_id,last_editor_name_snapshot=r.owner_name
      WHERE scheme_id=sid RETURNING * INTO s;
  END IF;
  INSERT INTO calc.quote_scheme_audit(scheme_id,action,from_status,to_status,actor_user_id,actor_name_snapshot,detail)
    VALUES(sid,'CONTRACT_GENERATED',previous_status,s.status,r.owner_user_id,r.owner_name,
      jsonb_build_object('source_kind',p_kind,'contract_record_id',p_record_id,'source_version',source_version,'contract_amount',amount));
  RETURN jsonb_build_object('scheme_no',s.scheme_no,'status',s.status,'lock_version',s.lock_version,'version_no',s.version_no,'source_kind',s.source_kind,'contract_record_id',p_record_id);
END $$;
COMMENT ON FUNCTION calc.register_generated_contract(text,uuid,text) IS 'Called atomically after a new contract INSERT; no historical backfill, no quotation/export/outcome fabrication.';
COMMIT;
