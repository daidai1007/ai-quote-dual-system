# 完整辅材目录上线与旧辅材清理

完整辅材目录由两份源文件共同组成：

- `辅材BOM清单.xlsx`：16 个普通柜型配置、255 条 BOM 明细。
- `JK,JC,操作台辅材价格.xlsx`：JK、JC、JQ、JP/JS 超宽柜和操作台，共 72 条固定/尺寸价格。

新版本是 `cabinet-auxiliary-706c234a5de12a39-v2`。操作均在 Neon `production / Primary / neondb` 的 SQL Editor 中进行，每次只运行一个文件并检查结果。

1. 运行 `database/cabinet-auxiliary/web/00-preflight.sql`。
2. 运行 `database/cabinet-auxiliary/web/01-create.sql`，创建 V2 表和函数。
3. 运行 `database/cabinet-auxiliary/web/02-stage.sql`，导入完整目录。
4. 运行 `database/cabinet-auxiliary/web/03-validate.sql`。应看到 16 个 profile、255 条 BOM、72 条固定价格，重复和不支持规则查询均为 0 行或 0。
5. 运行 `database/cabinet-auxiliary/web/04-activate.sql`。
6. 运行 `database/cabinet-auxiliary/web/05-verify.sql`。应只有一个 ACTIVE 版本；示例值应为 JK `8.300000`、JQ SUS316 `301.200000`、JC 豪华型 `652.500000`。
7. 将本次程序修改由你提交到 GitHub，随后在 Render 部署该提交。健康检查中的 build/deployment 应为 `2026-09-11-complete-cost-catalogs-v5` / `20260911-complete-cost-catalogs-v5`。
8. 至少试算普通 BOM 柜、JK、JC 豪华/标配、JQ、JP/JS 超宽柜、操作台各一条，并检查公式法辅材成本；快速报价规则不变。
9. 运行本目录 `00-readonly-plan.sql`。函数列表必须为空；若仍有函数引用旧辅材表，停止清理。
10. 运行 `01-delete-legacy-auxiliary.sql`。脚本不使用 `CASCADE`，发现未知依赖会整批回滚。
11. 运行 `02-readonly-verify.sql`。`legacy_auxiliary_cleanup_state` 应为 `PASS`，ACTIVE 目录应为 16 / 255 / 72。

源表没有提供 JC 和 JP/JS 超宽柜的不锈钢辅材价格。这些组合会返回明确的缺规则错误，不会回退到已删除的旧数据。

