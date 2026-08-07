# AI Quote Dual System

面向钣金柜体的双报价系统，包含 PostgreSQL 计算规则、Node.js API 与 PySide6 Windows 桌面客户端。

一次输入产品、尺寸、材质、喷塑方式和附件后，系统可同时返回：

- **公式法报价**：由 PostgreSQL 统一计算材料、辅材、人工、附件、喷塑、管理费和总成本。
- **快速报价**：从独立经验价格库匹配同柜型尺寸；无经验值时返回“待补充经验值”，不以 0 元代替。

## 仓库结构

```text
api/                       Node.js HTTP API
desktop_client/            PySide6 桌面客户端
database/migrations/       PostgreSQL 增量迁移与计算函数
scripts/                   本地启动脚本
templates/                 本地报价单模板放置位置
tests/                     导出与计算相关回归测试
export_dual_quote_workbook.mjs  Excel 报价单导出器
```

## 隐私与数据说明

公开仓库**不包含**真实数据库口令、API 密钥、客户资料、PDF/CAD 图纸、历史订单、公司报价模板、材料与附件实时价格、经验价格库以及构建产物。

克隆仓库后，需要导入你自己的脱敏业务数据。不要把 `.env`、`client_config.json` 或数据库备份提交到 Git。

## 环境要求

- Windows 10/11
- PostgreSQL 16–18（需要 `psql`）
- Node.js 20 或更高版本
- Python 3.11/3.12
- PDF 图纸识别可选安装 Poppler，并把 `pdftoppm` 加入 PATH

Excel 导出器当前使用 `@oai/artifact-tool`。在没有该运行库的环境中，报价计算和客户端仍可开发，但正式 Excel 导出需要提供兼容运行库或将导出器替换为其他实现。

## 快速开始

### 1. 配置 PostgreSQL

创建开发数据库，并按依赖顺序执行 `database/migrations/` 中需要的脚本。迁移不会自动载入真实业务价格。

### 2. 配置环境

复制 `.env.example` 中的变量到当前 PowerShell 环境。不要把真实口令写回示例文件。

```powershell
$env:PGPASSWORD = "你的本地 PostgreSQL 口令"
$env:PSQL_PATH = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
```

如需 API 密钥，可设置 `AI_QUOTE_API_KEY`，并复制 `client_config.example.json` 为 `client_config.json` 后填入相同密钥。

### 3. 启动 API

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-api.ps1
```

健康检查：

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/health"
```

### 4. 启动客户端

首次运行会建立 `.venv` 并安装依赖：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-client.ps1
```

### 5. 报价单导出

将已脱敏且字段兼容的模板命名为 `templates/quote_template.xlsx`。公开仓库不会附带原公司的内部模板。

## 开发约束

- 成本公式由 PostgreSQL 执行，API 与桌面端只做输入校验、流程编排和结果展示。
- 公式法与快速报价使用独立的数据表和函数。
- 所有尺寸匹配都必须明确记录匹配方法、来源尺寸和风险提示。
- 变更数据规则时应同时增加回归测试。

## 许可证

[MIT License](LICENSE)
