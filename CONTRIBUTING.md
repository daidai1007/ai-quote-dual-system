# Contributing

欢迎提交 Issue 和 Pull Request。

提交前请确认：

1. 未加入口令、密钥、客户名称、图纸、历史订单或真实价格数据。
2. `node --check api/server.mjs` 和 Python 语法检查通过。
3. 数据库修改放在 `database/migrations/`，不要覆盖已有迁移。
4. 计算逻辑优先放在 PostgreSQL 中，API 和桌面端避免复制同一套公式。
5. 新增业务规则时同时补充回归测试与说明。
