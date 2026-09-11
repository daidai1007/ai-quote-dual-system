# 完整喷塑目录上线与旧经验喷塑清理

完整喷塑 V2 由两份源文件组成：

- `JS,JP,JA,JE,JK,JM面积公式.xlsx`：普通柜 202 条面积公式。
- `产品喷塑经验值表.xlsx`：JC、JQ、JP/JS 超宽柜和操作台共 46 条固定/尺寸价格。

目标版本是 `cabinet-spray-4b3d73c9cb7a6f26-v2`。当前要求是先完善数据库，统一上线验收后再清理，因此现在不要单独激活或删除。

统一上线时，在 Neon `production / Primary / neondb` 的 SQL Editor 中每次完整运行一个文件：

1. 运行 `database/cabinet-spray/web/00-preflight.sql`。
2. 运行 `database/cabinet-spray/web/01-create.sql`。
3. 运行 `database/cabinet-spray/web/02-stage.sql`。
4. 运行 `database/cabinet-spray/web/03-validate.sql`，确认 202 条面积规则、46 条固定价格、6 个面积产品族和 5 个经验产品代码，重复查询均为 0 行。
5. 由你提交 GitHub，并在 Render 部署 `2026-09-11-complete-cost-catalogs-v5`。
6. 使用总切换脚本 `database/online-rollout-20260911/01-activate-current-catalogs.sql` 一次性激活五个目录，不单独运行喷塑 `04-activate.sql`。
7. 试算普通柜、JC 豪华/标配、JQ、JP/JS 超宽柜和操作台；核对精确尺寸、非标周长换算、不喷塑为 0、保存重开和导出。
8. 运行本目录 `00-readonly-plan.sql`。函数引用列表和依赖视图列表必须为空。
9. 运行 `01-delete-legacy-spray.sql`。脚本不使用 `CASCADE`，未知依赖会使事务回滚。
10. 运行 `02-readonly-verify.sql`。清理状态应为 `PASS`，活动目录应为 202 / 46；示例值应为 JQ SECC `49.500000`、操作台 SUS316 `34.000000`、JC 豪华型 `86.000000`。

源表未标材质的 JC 和 JP/JS 超宽柜按 SECC 保存。选择 SUS304/SUS316 时会返回明确缺规则错误，不会读取旧数据。

