# 报价单详情直接生成合同

入口顺序：打印、导出报价单、生成合同、调整报价。人员首次生成报价单且确认可直接采用时，点击“生成合同”即可，无需先调整、修订、打印或导出报价单。

## 配套 API

- 新增 `POST /api/quote-schemes/:schemeNo/confirm-for-contract`。请求包括当前快照、`expected_version` 并发锁、界面 `quote_version` 和 UUID4 `request_id`，沿用姓名会话与报价写权限。
- 初次未登记编号的报价先按原接口保存草稿；合同确认在原表中冻结当前正式快照，并写 `CONTRACT_CONFIRMED` 审计。不新增 PRINT/XLSX 导出成功记录，不冒充文件已输出。
- 复用原正式快照保存的并发检查、订单性质与已确认历史保护；只确认外部 DRAFT/REVISING 的当前内容。原内部、待分类、作废、他人不可操作报价仍受限制。
- `has_successful_export` 是既有流程使用的正式留存标记；合同确认也置为真以保留既有状态机兼容性。实际打印、导出次数仍由原 `quote_scheme_export` 记录决定，合同确认不向该表插入记录。
- 相同确认编号与相同内容重试返回既有结果；相同编号对应不同快照会拒绝。
- 既有 `/export-result` 接口仍只接受 PRINT/PREVIEW/XLSX，不能通过传入 CONTRACT 绕过新入口检查。

## 版本绑定

界面版本 `quote_management.current` 与数据库正式快照 `version_no`、并发 `lock_version` 分开处理。合同来源列表/详情新增 `quote_version`；数据库引用仍使用真实 `version_no`。例如界面 V3 可能对应数据库正式快照 2：按 V3 精确选择快照 2，不能用数字 3 直接查数据库。

当前已正式登记的历史版本直接使用其原快照，不重新计价或确认。未找到当前版本时保留当前页面并提示，不切换最新/其他版本。旧 API 缺少版本对应信息时明确停止该入口。

合同生成快照附加 `source_quote_version`，原 `source_version` 与数据库外键继续保存服务器编号；合同来源显示、历史记录和模板字段显示界面版本。

## 部署与边界

本项不新增数据库表、字段或迁移；使用既有报价方案、审计和合同模板表。需要先更新上述 API 与合同来源版本信息，再发布客户端。前一项台账合同功能所需迁移仍按其交接执行。

草稿自动保存尚在进行时，界面等待其完成后继续；准备合同期间锁定当前报价，失败则恢复操作并保留数据。生成合同仍使用原客户模板、字段核对、预览、打印与导出流程。

测试：`npm run test:quote-detail-contract`；`npm run test:quote-detail-contract:client`。均使用合成记录与一次性本地 PostgreSQL，不操作线上数据库、现有客户端或正式构建产物。
