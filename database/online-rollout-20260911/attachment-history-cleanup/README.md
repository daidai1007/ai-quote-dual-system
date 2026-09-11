# 旧附件历史与目录清理：人工执行步骤

本步骤适用于当前维护决定：暂不进行完整报价验收，允许删除旧报价引用的附件明细，先清理旧附件数据。

## 清理结果

- 删除 `attachment_selection` 中全部旧式附件选择记录，即 `calculation_status IS NULL` 的行。
- 删除全部 `data_version IS NULL` 的旧附件价格、分类以及可能存在的旧规则绑定。
- 在同一事务中把已验收的 `xlsx-7b6fcb18de6f8969-r4` 切换为唯一活动附件目录，活动行固定为 226 条。
- 保留所有 V2 附件快照、V2 报价行环境快照和 `dual_quote_result` 报价主体。
- 柜体材料、喷塑、辅材和人工目录保持 `STAGED`，本步骤不修改并柜拆分、数量、折扣、运费或汇总规则。

删除旧式 `attachment_selection` 后，历史报价仍可存在，但其中的旧附件明细和旧附件金额来源无法再从附件表恢复。

## 执行前

1. 暂停客户端报价操作并保持维护窗口。
2. 在 Neon 的 `production` 项目中，从当前 `Primary` 创建一个清理前备份分支，建议名称为 `backup-before-attachment-cleanup-20260911`。
3. 在 SQL Editor 再次确认选择的是 `production`、`Primary`、数据库 `neondb`。
4. 新建查询，完整粘贴并运行 `00-readonly-plan.sql`。
5. 确认：
   - r4 版本为 `STAGED`；
   - r4 行数为 226，活动行数为 0；
   - `v2_orphans_before_cleanup` 为 0；
   - 引用 `attachment_price` 的外键来源只包括 `attachment_classification`、`attachment_selection` 和 `attachment_cost_rule_binding`。
6. 保存预检结果。预检中的 `legacy_selection_rows_to_delete` 是将失去附件明细的旧历史行数。

若上述任一项不符，停止，不运行写脚本。

## 执行清理

1. 新建 SQL Editor 查询页。
2. 完整粘贴 `01-clean-and-activate-r4.sql`，不要只选择其中一部分。
3. 点击一次 **Run**。
4. 确认最后一个语句 `COMMIT` 显示成功。
5. 预期最终结果：
   - `attachment_price_total = 226`；
   - `attachment_price_active = 226`；
   - `legacy_price_rows = 0`；
   - `legacy_selection_rows = 0`；
   - r4 状态为 `ACTIVE`。

脚本包含事务和断言。任何错误都会阻止提交；若 SQL Editor 显示事务失败，单独运行 `ROLLBACK;`，保留错误文本，不要改成 `CASCADE` 后重试。

## 清理后复核

1. 新建查询，完整运行 `02-readonly-verify.sql`。
2. 必须看到：
   - `attachment_cleanup_state = PASS`；
   - `active_prices_missing_classification = 0`；
   - `orphan_attachment_selections = 0`；
   - 四个柜体公式目录仍为 `STAGED`。
3. 打开 Render 的 `/health`，确认 `attachment_contract = 2` 且 `attachment_ganged_ready = true`。
4. 本阶段不做完整报价。清理确认后结束维护窗口；后续报价验收和其余四个目录激活另行执行。

## 回退

写脚本提交前报错时，事务会自动保持旧状态。若提交后需要恢复，使用执行前创建的 Neon 备份分支核对并恢复；不要手工猜测旧附件价格或重新生成旧历史快照。
