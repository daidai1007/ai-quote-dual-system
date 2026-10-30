# 合同状态自动流转：人工更新说明

本说明只供人工更新；本次开发未操作业务数据库、构建客户端或发布任何服务。

## 生效范围

- 仅后续通过新版 API **成功生成**的合同生效。保存草稿、预览、上传模板和查看历史均不改变状态。
- 报价来源合同：当前正式版本的方案自动为 `CONTRACT / 合同`。旧版本的合同仅登记关联，不覆盖当前修订版。
- 台账来源合同：每份新合同进入一个 `LEDGER_CONTRACT` 类型报价方案，状态为合同，可查看实际合同。沿用生成者的本人/全部报价权限。
- 不回填历史合同。不伪造报价导出成功、公式成本、快速报价或成交结果。台账合同金额按实际合同快照保存。
- 合同方案可在报价方案、报价管理和分析的状态筛选中查询。报价来源仍可按原流程修订、导出。台账合同不进入报价计算编辑。
- 合同数量和金额单独显示；现有正式报价、成本和折扣统计规则保留。按产品不能可靠拆分的合同金额显示 `—`。

## 更新前

1. 总修改先合并并回归。此补丁基于 `b6e864da7f29291957af9f2181d207e1e903e4f8`，包含前两项未合并修复的基础：台账本机读取解耦、无对应客户模板时借用其他可用模板。不得覆盖这些改动。
2. 记录当前 Git 版本，完整备份数据库及当前 API 版本。确认数据库连接目标；不要在命令或日志中输出口令。
3. 确认已具备报价方案、客户合同模板、Excel 台账合同的原有数据库迁移。新增功能需要**数据库脚本 + API + 客户端源码配套更新**，仅更新 API 无法显示客户端新筛选及状态。
4. 使用已有人工数据库连接，先执行只读预检：

```sh
psql --set ON_ERROR_STOP=on --file database/migrations/contract_scheme_status_v1.preflight.sql
```

若预检缺少原有表/函数，先解决前置迁移；自定义状态约束须先人工审查，新迁移不会默默删除不认识的状态规则。

## 数据库人工步骤（本次不执行）

在维护窗口暂停新合同生成并确认无在途生成请求；先在测试库演练以下步骤，再由负责人决定执行：

```sh
psql --set ON_ERROR_STOP=on --file database/migrations/contract_scheme_status_v1.sql
psql --set ON_ERROR_STOP=on --file database/migrations/contract_scheme_status_v1.verify.sql
```

此迁移扩展两处状态约束，向方案增加合同来源/关联元数据，新增不可修改的合同关联表、登记函数和保护触发器；不遍历历史合同创建方案，不修改原有金额及快照。已有方案的来源标识默认为 `QUOTE`。

若迁移账号与 API 账号不同，为**实际 API 角色**配置新增对象权限；以下 `API_ROLE` 是占位符，必须换成现有角色，不要另建账号或照抄占位符执行：

```sql
GRANT SELECT,INSERT ON calc.quote_scheme_contract_link TO "API_ROLE";
GRANT USAGE ON SEQUENCE calc.quote_scheme_contract_link_link_id_seq TO "API_ROLE";
GRANT EXECUTE ON FUNCTION calc.register_generated_contract(text,uuid,text) TO "API_ROLE";
```

登记函数为 `SECURITY INVOKER`，沿用 API 角色原有报价方案、快照、条目、版本、审计及编号函数权限；另需确认其能读取合同和台账合同表。用 API 角色重新执行 verify，`can_link/can_number_link/can_register` 全部应为真，`invalid_scheme_contract_links` 应为 0。

## API 通过 GitHub 人工更新

迁移完成后，推送总修改验收后的提交，并在现有 GitHub 部署流程中人工选择该提交更新 API。本任务不运行部署。

需要同步的 API 文件：

- `api/contract_status.mjs`（新增）
- `api/contract_service.mjs`
- `api/contract_ledger_service.mjs`
- `api/quote_scheme_service.mjs`
- `api/quote_analysis_service.mjs`
- `Dockerfile`、`.dockerignore`（新模块打包白名单）

若此前模板兜底未合并，还要按前项交接同步 `api/contract_template_policy.mjs` 等依赖。不要只上传单个服务文件。数据库迁移文件须由人工数据库流程执行，API 启动不会自动迁移。

新 API 检测不到配套登记函数时，会提示合同功能尚未启用；避免生成合同成功但状态未登记。不要在迁移尚未完成时更新 API。

## 客户端后续配套（当前不构建、不发布）

同步源码：`contract_management.py`、`contract_ledger_ui.py`、`quote_scheme_center.py`、`quote_management.py`、`quote_analysis.py`、`quote_detail_contract.py`、`quote_delivery.py`、`scheme2_ui.py`。保留现有控件与弹窗。新合同状态采用浅紫色标记。

客户端构建、开发电脑覆盖及服务器客户端发布须另行安排。旧客户端不具备新状态的完整交互支持，应在配套客户端验收后再开放新功能给操作人员。

## 人工验收

1. 新报价生成合同：方案显示合同；原报价价格、附件、运费及历史版本不变，原有导出/修订正常。
2. 从历史正式版本生成合同：保留关联，但当前较新修订状态不被覆盖。
3. 台账一次生成多份合同：每份一个合同方案；重试同一请求不重复生成；查看合同打开对应实际文件，费用不进入虚构报价/成本统计。
4. 报价方案、报价管理、报价分析均能筛选合同。分析合同数量和金额正确，未自动登记成交。
5. 本人范围不能看到其他人的方案；全部报价范围只读查看仍保留原文件输出权限限制。
6. 查看更新前历史合同：不新增方案、不补改状态。台账导入和跨客户模板借用原功能继续可用。

## 回退

先停新生成请求。**只在尚无任何新合同关联/合同状态/台账方案时**，才可人工执行 `contract_scheme_status_v1.rollback.sql` 并回退配套 API/客户端源码。该脚本锁表复核后才移除本次空结构；不会删除合同或方案。

已经产生新合同数据时，回退脚本会明确拒绝并整体回滚。保留数据库结构和记录，采用向前修复；不得删除关联或把合同批量改回已报价。数据库备份恢复属于另行评估的业务恢复操作，本说明不自动执行。
