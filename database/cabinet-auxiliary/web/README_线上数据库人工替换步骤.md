# 线上柜体辅材目录人工替换步骤（2026-09-17）

## 本次数据

- 新版本：`cabinet-auxiliary-189ae4efbfcb40f5-v3`
- BOM：`辅材BOM清单.xlsx`
  - SHA-256：`62b474d977ea512096e2099098e30fcbff91940fdcf2107f37854eb8f1a00125`
- 固定价格：`JK,JC,操作台辅材价格.xlsx`
  - SHA-256：`4505363a41d6a2ba65587c5df25ac9e00a7ff24c330980ded6357084180de5be`
- 合并源 SHA-256：`189ae4efbfcb40f50260a69f389e224771d13eff44c6cbebbe49ae0dad0bb586`
- 预期数据量：32 个材质门型配置、510 条 BOM 明细、72 条固定/尺寸价格。
- JA、JE 单门的吊环新增严格高度规则：高度大于 1000 mm 时数量为 2，否则为 0；适用于 SECC、SUS304、SUS316。
- JE 单门 SUS304/SUS316 的吊环单价修正为 `5.50`；同配置两条锁杆单价继续保持 `5.80`。

## 必须先部署的程序改动

新 BOM 同一产品和门数组合分别包含 SECC、SUS304/SUS316 两套规则。服务器查询必须使用 `material_code` 过滤 `cabinet_auxiliary_profile.material_codes`。如果未部署新版 `api/cabinet_auxiliary_service.mjs`，不要激活 V3 数据，否则普通柜报价会因同时命中两个 profile 而失败。

建议顺序：先执行 00、01；再部署程序；然后执行 02、03、04、05。

## Neon SQL Editor 操作

每个 SQL 文件单独新建一个查询页并执行。必须等上一份执行成功后再继续。

1. 执行 `00-preflight.sql`。
   - 确认数据库为 production/neondb。
   - 记录当前 `ACTIVE` 的 `data_version`，用于人工回滚核对。
   - 预检只读，不修改数据。

2. 执行 `01-create.sql`。
   - 增加 BOM profile 的 `material_codes` 字段及索引。
   - 保留并兼容当前 ACTIVE V2 数据；旧 profile 会临时标记为同时适用 SECC/SUS304/SUS316。
   - 创建 V3 暂存及激活函数。

3. 部署包含材质筛选的新版服务程序。
   - 文件：`api/cabinet_auxiliary_service.mjs`。
   - 部署完成后，旧 ACTIVE V2 仍可继续报价。

4. 执行 `02-stage.sql`。
   - 导入新版本，但状态只会是 `STAGED`，不会影响线上报价。
   - 预期返回 `cabinet-auxiliary-5f0aa74619a28570-v3`。
   - 该文件较大，请整份执行，不要截断十六进制 payload。

5. 执行 `03-validate.sql`。
   - 新版本状态必须为 `STAGED`。
   - 产品统计必须为：JA 4/24、JE 4/24、JS 10/186、JP 10/246、JM 4/30（profile/line）。
   - 固定规则必须为：JK 26、JC_EXP 4、JQ_EXP 8、JP_WIDE_EXP 12、JS_WIDE_EXP 12、OP_TABLE_EXP 10。
   - 材质重复查询必须返回 0 行。
   - `unsupported_quantity_rules` 必须为 0。
   - 任一项不符时停止，不执行激活。

6. 执行 `04-activate.sql`。
   - 新 V3 变为 `ACTIVE`，此前的 ACTIVE 变为 `RETIRED`。
   - 激活在一个事务中完成。

7. 执行 `05-verify.sql`。
   - `active_versions` 必须为 1。
   - V3 必须显示 ACTIVE、32 profiles、510 lines、72 fixed_rules。
   - 材质重复查询必须返回 0 行。
   - 固定价格样例应返回有效数值。

8. 在实际程序中各做一组 SECC、SUS304、SUS316 报价。
   - 同一产品、尺寸和门型下，SECC 应命中无 `(2)` 的来源工作表；SUS304/SUS316 应命中带 `(2)` 的来源工作表。
   - 检查公式法结果中的 `cabinet_auxiliary_version` 为 V3。
   - 快速报价不应因本次辅材目录替换而变化。

9. 观察稳定后才可执行 `07-delete-retired.sql`。
   - 该步骤会删除旧版本及其明细；完成前不要执行，以便回滚。

## 回滚

如果激活后出现异常，立即执行 `06-rollback.sql`，它会将本次 V3 设为 RETIRED，并恢复最近一个旧版本为 ACTIVE。随后再次执行 `05-verify.sql`，确认 ACTIVE 版本只有一个。回滚后不要执行 `07-delete-retired.sql`。

## 已知来源限制

- `JK,JC,操作台辅材价格.xlsx` 本次未变化。
- JC、JP 超宽柜、JS 超宽柜的固定价格源仍只提供 SECC；选择 SUS304/SUS316 时应返回缺少规则，不能复用 SECC 价格。
