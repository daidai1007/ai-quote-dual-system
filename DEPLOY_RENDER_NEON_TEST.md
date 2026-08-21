# Render + Neon 测试环境人工部署

本目录用于 GitHub `main` 分支。部署范围是统一测试 API；客户端不得直接连接 Neon。

## 部署前置条件

1. Neon 已创建测试项目和测试数据库。
2. 本地完整业务库已用非池化连接迁移并完成对象、行数和业务回归。
3. GitHub `main` 分支包含本目录列出的 Docker 和 API 文件。
4. Neon 连接串、数据库口令和 API 密钥均未写入 GitHub。

完整业务库至少包括产品、柜型、材料及历史价格、喷塑价格、人工规则、辅材及 BOM、附件、快速报价经验、公司历史、报价结果、视图、函数、触发器、索引、约束和序列。

## Render 控制台设置

- New：`Web Service`
- Repository：`daidai1007/ai-quote-dual-system`
- Branch：`main`
- Runtime：`Docker`
- Dockerfile Path：`./Dockerfile`
- Health Check Path：`/health`
- Auto-Deploy：`On`（使用者人工推送 `main` 后由 Render 自动部署）

环境变量：

- `DATABASE_URL`：Neon 的 pooled 连接串，仅用于 API 日常运行。
- `AI_QUOTE_API_KEY`：自行生成的长随机值，必须与测试客户端一致。
- `AI_QUOTE_PSQL_TIMEOUT_MS`：建议 `45000`。
- `PGSSLMODE`：`require`。

不要手工设置 `PORT`；Render 会自动提供。不要把以上真实值提交到 `.env`、截图、聊天或 GitHub。

## 验证顺序

1. 打开 `https://你的服务.onrender.com/health`，确认：
   - `ok` 为 `true`
   - `build` 为 `2026-08-17-auxiliary-bom-v1`
   - `deployment` 为 `2026-08-21-unified-door-db-v3`
2. 使用 API 密钥请求 `/api/health/database`，确认 `ready` 为 `true`，且所有检查项均为 `true`。
3. 再依次验证产品目录、附件目录、公式报价、快速报价、配置变形、辅材明细、报价确认和 Excel 导出。
4. 全部通过后，才生成指向 Render 地址的测试客户端并发布 GitHub Release。

Render 的 `/health` 不查询数据库，避免平台的高频健康检查持续唤醒 Neon。数据库检查只在人工验收和回归时调用。

## 本次门型公式数据库同步

先在 Neon 建立恢复点或临时分支，再推送并等待 Render 显示 `Live`。人工推送命令：

```powershell
git -C "G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy" push origin main
Invoke-RestMethod "https://ai-quote-dual-test.onrender.com/health" | ConvertTo-Json
```

Free 实例不提供 Render Shell。先在 Neon 建立恢复点或临时分支，再打开
Neon Console 的 SQL Editor，载入并执行以下本地事务型迁移文件：

```
G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy\database\migrations\sync_unified_door_formula_templates.sql
```

执行前确认 SQL Editor 连接的是目标数据库；脚本以 `BEGIN` 开始、以
`COMMIT` 结束，断言失败时事务不会提交。不要把数据库口令粘贴到聊天或
提交到 GitHub。

迁移只同步 JS、JP、JA、JE 对应的 7 个公式模板，不修改快速报价经验表。执行完毕后，先检查 `/api/health/database`，再运行 `600×300×2000` 门型回归：

```powershell
Set-Location "G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy"
$env:AI_QUOTE_V3_CORE_ROOT="..\AIQuoteDualSystem\_internal\v3_core"
$env:QT_QPA_PLATFORM="offscreen"
& "G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe" `
  "tests\regress_cloud_door_matrix.py" `
  --config "..\AIQuoteDualSystem\client_config.json"
```
