# 附件 API、客户端兼容交付

本次是本地代码及验证交付。线上仍以用户提交的截图为依据：r4为STAGED，新目录226条、活动0条、成本规则62条；原活动目录249条，历史选择245条。没有连接线上数据库、部署API、切换目录、改写源Excel或覆盖当前客户端。

## 路径与范围

- 工作仓库：`G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy`。
- 当前客户端：`G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem`，现有 `AIQuoteDualSystem_layout_v6.exe` 未改。
- 已验证核心实际路径：`G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core`。
- 已验证 Python：`G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe`，Python 3.12 x64、PySide6。
- 已本地生成 `AIQuoteDualSystem_Installer\AIQuoteDualSystem_Setup_v2026.09.11.exe`；未安装、未分发。安装包使用仓库 `packaging/build_installer.ps1`、Python 3.12 x64 和已验证动态 V3 核心构建。
- 既有非本任务修改继续保留。并柜拆分、逐柜计算、金额汇总、数量、折扣和运费规则不改；新版附件在原并柜汇总后统一计算并保存一次快照。

## 实现结果

`api/attachment_service.mjs` 统一执行目录读取、报价环境取价、成本计算及快照持久化。`api/server.mjs` 接入V2目录、预览、单柜双报价和并柜汇总快照；确认、试确认、历史保存及导出均按报价行ID取回服务端快照。客户端传来的面价、规则ID和最终金额不作为计算依据。

每次成功提交计算生成新的UUID报价行，在 `attachment_selection` 中每次选择只插入一条。即使同一报价存在同型号产品、同一附件重复选择且人工尺寸不同，也分别保存。基础柜体仍调用原数据库报价函数，使用独立临时报价ID并回滚临时写入；随后单独事务保存附件环境及结果。不修改原柜体或并柜数据库函数。

历史记录直接查看或导出时继续使用原快照。打开附件编辑并重新计算时，已退出当前目录的旧附件需要重新选择，不按同名附件自动替换。本轮API适配使用已经准备的V2表及触发器，无需新增线上数据库迁移。

快速金额使用完整精度 `quick_face_price`；公式金额使用固定成本或统一安全解析器。环境中的密度、材料和喷塑价格由当前材质、喷塑方式、日期查询取得。固定成本不随动态参数改变。QUICK_ONLY明确排除公式合计，ERROR使公式总额不可用并阻止正式确认/导出。

动态成本的金额组成和单位成本统一保留8位小数，与已安装数据库快照校验口径一致，选择行金额最后保留2位。重量和面积不重复换算，Excel面价不经过组成成本的舍入；固定金额按源确认值保留。

`desktop_client/attachment_v2_client.py` 同时适配源码MainWindow和动态V3核心，分别从 `main.py`、`layout_refresh.py` 安装。沿用一套附件表，显示单位、面价、快速金额、公式状态/单价/金额和人工尺寸。人工尺寸通过双击填写，按选择保存；只对原允许的安装板开放加减方向。面价只读，旧规格匹配流程不得改写Excel面价。

产品、门型、尺寸、材质、喷塑、日期、型号、附件选择变化会使旧整柜报价失效；附件预览防抖重算并丢弃过期响应。确认完整报价仍需点击计算双报价。数量变化保留人工尺寸。界面和选项恢复按ID匹配，避免同名跨分类串用。辅材清单完整保存在提示、快照和导出中。

`attachment_snapshot_export.mjs` 增加“附件双报价明细”工作表：31列，包含报价行/选择ID、分类、名称/型号/单位、选择数量、符号、面价/快速金额、重量、材料/喷塑价格及成本、辅材金额/原文、人工、公式成本/金额、人工尺寸、状态、说明及版本。组成值按每单位、金额按选择行标注；最终柜体数量仍沿用原规则。固定成本不编造组成拆分。

沿用原产品人工倍率及管理费逻辑，附件人工不套用倍率，也不新增附件加价。原折扣与数量例外保留，公式附件部分改读独立公式金额。

## 接口及兼容约定

| 接口 | 行为 |
|---|---|
| `GET /health` | build 为 `2026-09-11-complete-cost-catalogs-v5`；返回 `attachment_contract:2`、`attachment_ganged_ready:true`，不查询数据库 |
| `GET /api/attachments/catalog?v=2` | 当前版本精确面价及绑定规则；无已启用目录时返回409 |
| `POST /api/attachments/preview` | 返回规则所需人工参数、各组成、两种金额、状态和错误；不保存选择 |
| `POST /api/quotes/calculate-dual` | `attachment_contract:2`启用V2；只传一个attachments数组；返回UUID报价行及附件选择ID |
| `POST /api/attachments/snapshot-ganged` | 接收原并柜子柜汇总结果，统一计算V2附件双金额并保存一条整套并柜快照；不重新计算或修改子柜结果 |
| confirm、confirm-check、company-history、export | V2按服务端冻结结果还原；环境/数量/人工参数变更须重算；错误不得确认或导出 |

附件请求项为 `attachment_price_id`、`quantity`、`attachment_price_sign`、`manual_inputs`；所属产品环境在请求外层提供。无新版附件的已有客户端流程保持旧接口语义。新客户端收到不带V2契约的附件报价响应会拒绝采用。

默认仅允许ACTIVE目录。兼容测试环境可明确设置：

```powershell
$env:AI_QUOTE_ATTACHMENT_V2_VERSION='xlsx-7b6fcb18de6f8969-r4'
$env:AI_QUOTE_ATTACHMENT_V2_ALLOW_STAGED='1'
```

这两个配置仅供隔离测试服务；不会切换目录。测试本地API时应明确指定本地数据库，清除可能继承的线上 `DATABASE_URL`，并将客户端 `AI_QUOTE_API_URL` 指向本地API。不要让测试客户端沿用默认Render地址。

启用新活动目录后，新API会拒绝旧附件目录/旧附件计算入口（426），阻止旧客户端把同一个合计用于两种报价。旧API进程自身没有这道门槛，所以必须先更新全部API实例、排空在途旧请求，再考虑目录切换。API角色需有新表读取、报价行/选择插入、相应序列使用及原取价函数执行权限；导入和切换函数不授予普通API角色。

**并柜兼容：包含V2附件的并柜报价不再拦截。客户端仍按现有流程逐个子柜调用原双报价接口且子柜请求不带附件，完成原汇总后再调用一次并柜附件快照接口。固定底座按原子柜索引使用对应尺寸；其他附件按整套并柜数量计算。保存、恢复、试确认、正式确认和导出均复用同一服务端快照。数据库并柜函数未修改。**

## 本地验证

1. Node/API/客户端合同/导出回归最终 84/84 通过，包含原安装板符号、附件数量、折扣、并柜导出和部署文件清单。
2. 附件与四类柜体成本目录的独立 PostgreSQL 验证最终 32/32 通过。使用127.0.0.1:55439临时测试库，测试生成合成报价，不读取真实历史数据。30条实际动态附件源规则逐条通过服务端计算及数据库快照校验；同一底座选择分别输入100/200mm也成功保存为不同选择ID和成本。
3. 实际 `api/server.mjs` HTTP → psql → 本地PostgreSQL链路验证：按ID计算、客户端篡改金额无效、原产品计算临时写入回滚、单柜及并柜V2选择持久化、并柜子柜尺寸快照校验、试确认回滚、正式保存、历史读取及旧客户端426门槛。测试的柜体基础函数是明确的合成桩，仅附件迁移/规则/快照路径为真实实现；不声称复核了所有线上柜体公式。
4. 源码与动态V3分别运行离线Qt测试，使用数据库测试生成的真实响应夹具，替换网络I/O：选择、人工尺寸、数量重算、面价精度、错误清除、请求字段、保存重开、过期响应拒绝、ERROR阻断及并柜V2选择通过。V3并柜布局测试验证原两个子柜请求内容不变，只新增一个汇总快照请求。未请求Render。
5. 原客户端默认参数、附件规格、产品规则、迁移公式及V3完整界面套件最终通过。过程中曾有一次模板重试计数时序断言失败（3次/预期2次）；最终完整复跑通过。新版环境预览明确限定为含V2标记的选择，保留旧请求和原重试规则。
6. 代表性导出使用服务端保存后的快照：相同产品名称的两个独立报价行（SECC、SUS304），覆盖固定成本、动态成本、仅快速报价、辅材文本。核验4条附件明细的归属ID、原文和空公式金额。

复现命令（在工作仓库运行）：

```powershell
npm run check
npm test
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test_attachment_database.ps1
npm run test:client
$env:AI_QUOTE_V3_CORE_ROOT='G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core'
$env:PYTHONIOENCODING='utf-8'
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' tests/verify_attachment_v2_client.py
& 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' tests/verify_attachment_v2_client.py --source
```

附件数据库测试先运行，因为Qt测试读取其生成的 `api-client-fixtures.json`。日志、夹具、截图与导出位于 `test-output/attachment-cost-v2/`。

可审查文件：`api-snapshot-export.xlsx`、对应 `api-snapshot-export.json`，以及 `client-v3-attachment.png`、`client-source-attachment.png`。示例使用本地合成柜体基础成本及材料/喷塑测试价格，仅用于验证。

源Excel本次核对SHA-256仍为 `7b6fcb18de6f896942a627f70abbd91ba4e5587ed87e57abe837b4c03f043a64`。映射结果保持226快速、62规则、264绑定、9材质关系，8条快速独有；未新增未决映射。具体源行及确认转换见 `generated/source-row-mapping.md`。

## 后续人工顺序（本次不执行）

1. 审查本地代码、示例和并柜兼容结果。无需重新清除目录、导入r4或重做已完成的数据库准备。
2. 获准后先在隔离验收环境安装当前代码/API和新客户端，核对实际API角色权限、原产品函数签名、材料/喷塑日期取价及完整确认导出链路。
3. 验收后另行发布API与客户端；API所有实例升级并排空旧请求，旧客户端停止提交新附件报价。本地Docker白名单已包含新增模块，2026.09.11安装包已构建但尚未分发。
4. API与客户端完成部署后，先验收单柜和并柜各一笔V2附件报价；确认健康状态、保存重开、试确认和导出均通过，再在获得目录切换授权后按 `线上人工执行步骤.md` 第5节对已STAGED的r4调用switch；不重复stage，不清空选择历史。
5. 切换事务可能等待目录写锁，使用既有5秒锁超时；超时回滚后择时重试。普通读取在提交前看到旧目录，提交后看到新目录。重新核验活动226条、原历史保留及实际单柜、并柜报价。

当前继续停在本地审查阶段。
