BEGIN;

CREATE TABLE IF NOT EXISTS calc.client_order_workspace (
  order_number TEXT PRIMARY KEY,
  workspace_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE calc.client_order_workspace IS
  '桌面客户端按订单号保存的选项配置、成本计算和报价单工作区数据';

COMMIT;
