# 双报价计算接口

接口不在程序中重复实现成本公式，只调用 PostgreSQL 的 `calc.calculate_dual_quote(...)`，并返回公式法、快速报价、匹配经验记录和风险提示。正式报价单导出使用根目录锁定的 Node.js 依赖。

## 启动

先在 PowerShell 设置数据库密码（只对当前窗口有效）：

```powershell
$env:PGPASSWORD = "你的postgres口令"
$env:PSQL_PATH = "G:\PostgreSQL\18\bin\psql.exe"
node .\api\server.mjs
```

如实际安装目录不同，只需修改 `PSQL_PATH`。默认监听 `http://127.0.0.1:8080`。

## Render + Neon

云端运行优先读取 Render 的 `PORT` 和 Neon 的 `DATABASE_URL`。Docker 镜像会监听 `0.0.0.0`、安装 Linux 版 `psql` 并强制 PostgreSQL SSL。公网监听必须设置 `AI_QUOTE_API_KEY`，否则 API 会拒绝启动。

具体人工部署步骤见根目录 `DEPLOY_RENDER_NEON_TEST.md`。

## 接口

`POST /api/quotes/calculate-dual`

必填字段：`quote_id`、`product_code`、`material_code`、`width_mm`、`height_mm`、`depth_mm`。

门型产品同时传入 `single_door_count` 和 `double_door_count`。JS、JP、JA、JE
公式产品支持 `1/0`、`0/1`、`0/2`、`2/0`、`1/1` 五种组合，
单/双门数量会进入数据库公式模板控制单元，从而分别计算重量和产品面积。
其他门型产品仅接受 `1/0` 和 `0/1`，分别使用数据库单门和双门产品。

快速报价只区分单门和双门：`0/1`、`0/2` 为双门，`1/0`、`2/0`、`1/1`
为单门。门型加价由 API 响应层自动处理，不修改公式法结果。

公式法使用的标准柜体重量和喷涂面积可通过 `base_material_weight_kg`、`product_area_m2` 传入；如果未传入，接口仍会返回快速报价，同时在 `risk_flags` 中返回公式数据缺失提示。

附件数组示例：

```json
"attachments": [
  { "model_code": "JP466060", "quantity": 1 }
]
```

快速报价未匹配经验值时，`quick_quote.total_cost` 为 `null`，并返回 `quick_quote_missing` 风险，不会按 0 元处理。

`GET /api/products/catalog` 返回产品、数据库型号、材质和喷塑选项。

`GET /api/attachments/catalog` 读取附件库，并返回独立的
`category_level1`、`category_level2`、`category_level3` 分类字段；
`POST /api/attachments/catalog`
新增一条持久附件。新增请求至少包含 `item_name` 和非负 `price`。

## 快速检查

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```
