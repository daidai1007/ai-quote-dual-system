-- 报价方案中心 V1。
-- 只通过人工部署执行；桌面客户端和 API 都不会自动运行本迁移。
BEGIN;

CREATE TABLE IF NOT EXISTS calc.quote_scheme_daily_counter (
  business_date DATE PRIMARY KEY,
  last_value INTEGER NOT NULL CHECK (last_value BETWEEN 1 AND 999999)
);

CREATE OR REPLACE FUNCTION calc.next_quote_scheme_number()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
  v_date DATE := (clock_timestamp() AT TIME ZONE 'Asia/Shanghai')::date;
  v_value INTEGER;
BEGIN
  INSERT INTO calc.quote_scheme_daily_counter (business_date, last_value)
  VALUES (v_date, 1)
  ON CONFLICT (business_date) DO UPDATE
    SET last_value = calc.quote_scheme_daily_counter.last_value + 1
    WHERE calc.quote_scheme_daily_counter.last_value < 999999
  RETURNING last_value INTO v_value;
  IF v_value IS NULL THEN
    RAISE EXCEPTION 'daily quote scheme number exhausted for %', v_date;
  END IF;
  RETURN 'BJ-' || to_char(v_date, 'YYYYMMDD') || '-' || lpad(v_value::text, 6, '0');
END;
$$;

CREATE TABLE IF NOT EXISTS calc.quote_scheme (
  scheme_id BIGSERIAL PRIMARY KEY,
  scheme_no TEXT NOT NULL UNIQUE
    CHECK (scheme_no ~ '^BJ-[0-9]{8}-[0-9]{6}$'),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'QUOTED', 'REVISING', 'ARCHIVED', 'VOID')),
  version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
  source_version_no INTEGER CHECK (source_version_no IS NULL OR source_version_no > 0),
  source_scheme_id BIGINT REFERENCES calc.quote_scheme(scheme_id),
  company_name TEXT NOT NULL DEFAULT '',
  product_summary TEXT NOT NULL DEFAULT '',
  quoted_amount NUMERIC(18,2),
  creator_user_id TEXT NOT NULL,
  creator_name_snapshot TEXT NOT NULL,
  creator_department_id TEXT,
  last_editor_user_id TEXT NOT NULL,
  last_editor_name_snapshot TEXT NOT NULL,
  lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
  has_successful_export BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  quoted_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ,
  voided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_quote_scheme_creator_updated
  ON calc.quote_scheme (creator_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_quote_scheme_department_updated
  ON calc.quote_scheme (creator_department_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_quote_scheme_status_updated
  ON calc.quote_scheme (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_snapshot (
  scheme_id BIGINT PRIMARY KEY REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  snapshot_payload JSONB NOT NULL,
  snapshot_schema_version INTEGER NOT NULL DEFAULT 1,
  saved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  saved_by_user_id TEXT NOT NULL,
  saved_by_name_snapshot TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_version (
  scheme_id BIGINT NOT NULL REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  version_no INTEGER NOT NULL CHECK (version_no > 0),
  source_version_no INTEGER,
  status TEXT NOT NULL CHECK (status IN ('QUOTED', 'ARCHIVED', 'VOID')),
  snapshot_payload JSONB NOT NULL,
  quoted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (scheme_id, version_no)
);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_item (
  scheme_id BIGINT NOT NULL REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL CHECK (line_no > 0),
  item_payload JSONB NOT NULL,
  PRIMARY KEY (scheme_id, line_no)
);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_share (
  scheme_id BIGINT NOT NULL REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  grantee_user_id TEXT NOT NULL,
  granted_by_user_id TEXT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (scheme_id, grantee_user_id)
);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_audit (
  audit_id BIGSERIAL PRIMARY KEY,
  scheme_id BIGINT NOT NULL REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  actor_user_id TEXT NOT NULL,
  actor_name_snapshot TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quote_scheme_audit_scheme
  ON calc.quote_scheme_audit (scheme_id, created_at DESC, audit_id DESC);

CREATE TABLE IF NOT EXISTS calc.quote_scheme_export (
  export_id BIGSERIAL PRIMARY KEY,
  scheme_id BIGINT NOT NULL REFERENCES calc.quote_scheme(scheme_id) ON DELETE CASCADE,
  export_kind TEXT NOT NULL CHECK (export_kind IN ('PRINT', 'PREVIEW', 'XLSX')),
  succeeded BOOLEAN NOT NULL,
  actor_user_id TEXT NOT NULL,
  actor_name_snapshot TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION calc.quote_scheme_creator_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.creator_user_id IS DISTINCT FROM OLD.creator_user_id
     OR NEW.creator_name_snapshot IS DISTINCT FROM OLD.creator_name_snapshot
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.scheme_no IS DISTINCT FROM OLD.scheme_no THEN
    RAISE EXCEPTION 'quote scheme creator and number are immutable';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_quote_scheme_creator_immutable ON calc.quote_scheme;
CREATE TRIGGER trg_quote_scheme_creator_immutable
BEFORE UPDATE ON calc.quote_scheme
FOR EACH ROW EXECUTE FUNCTION calc.quote_scheme_creator_immutable();

COMMENT ON TABLE calc.quote_scheme IS
  '报价方案主记录；创建人由 API 的受信身份映射写入且不可修改。';
COMMENT ON TABLE calc.quote_scheme_snapshot IS
  '当前完整报价快照；历史打开、打印和导出必须读取此快照，不重新按现价计算。';
COMMENT ON TABLE calc.quote_scheme_version IS
  '同一主方案编号下的不可变 V1/V2 历史快照；创建修订版不生成新方案编号。';
COMMENT ON TABLE calc.quote_scheme_item IS
  '按显示顺序拆分保存的报价行快照，便于审计和查询。';

COMMIT;
