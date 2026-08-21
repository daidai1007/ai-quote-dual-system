# `test` 分支人工上传清单

本目录是白名单部署补丁，不是完整 Git 仓库。GitHub 网络不可用时，可在网页端切换到 `test` 分支后按下列路径新增或替换文件；未列出的现有文件保持不变。

## 新增或替换

- `.dockerignore`
- `.env.render.example`
- `Dockerfile`
- `DEPLOY_RENDER_NEON_TEST.md`
- `DEPLOYMENT_MANIFEST.sha256`
- `package.json`
- `package-lock.json`
- `exceljs_range_adapter.mjs`
- `quote_export_contract.mjs`
- `export_dual_quote_workbook.mjs`
- `api/server.mjs`
- `api/attachment_rules.mjs`
- `api/attachment_catalog_rules.mjs`
- `api/door_variant_rules.mjs`
- `api/runtime_config.mjs`
- `api/runtime_config.test.mjs`
- `api/cloud_liveness.test.mjs`
- `api/attachment_rules.quick_only.test.mjs`
- `api/attachment_catalog_rules.test.mjs`
- `api/door_variant_rules.test.mjs`
- `api/README.md`

## 不得上传

- `.env` 或真实 Neon 连接串
- `client_config.json` 或真实 API 密钥
- PostgreSQL dump/backup
- 客户图纸、OCR 临时文件、原始 Excel
- `node_modules`、本地日志、构建目录和已安装客户端

## 上传前本地验证

在包含 `package.json` 的目录执行：

```powershell
npm.cmd run verify
```

只有检查和测试均通过，才提交到 `test` 分支。Render 应设置为人工部署，不能在代码尚未完成数据库迁移和接口回归时合并进 `main`。
