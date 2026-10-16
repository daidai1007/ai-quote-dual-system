BEGIN;

CREATE TABLE IF NOT EXISTS calc.client_diagnostic_report (
  report_id UUID PRIMARY KEY,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  client_version TEXT NOT NULL DEFAULT '',
  order_number TEXT NOT NULL DEFAULT '',
  report_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS client_diagnostic_report_submitted_at_idx
  ON calc.client_diagnostic_report (submitted_at DESC);

COMMENT ON TABLE calc.client_diagnostic_report IS
  '由桌面用户主动确认提交的报价诊断报告；包含详细报价，90 天后于下次提交时清理。仅数据库管理员查询。';

COMMIT;
