# Public release validation

Validated before the initial public-source release:

- Node.js syntax: `api/server.mjs`
- Node.js syntax: `export_dual_quote_workbook.mjs`
- Python syntax: `desktop_client/main.py`
- JSON syntax: public example configuration and request fixtures
- Secret scan: no production password, API key, customer record, local user path, or private drawing/template is included
- Git ignore rules: local configuration, virtual environments, build output, database backups, drawings, spreadsheets, and generated executables are excluded

## Excel exporter limitation

The Excel exporter currently imports `@oai/artifact-tool`. That runtime is not distributed in this repository. The calculation API and desktop client can still be developed without it, but workbook-export regression tests require a compatible implementation of that package or a replacement exporter.

## Data limitation

Migration files define schema and calculation behavior only. Real material prices, attachment prices, formula workbooks, customer history, drawings, and quick-quote experience data must be supplied separately with sanitized test data or local business data.

## Door variant and attachment rules

Run the source regression with:

```powershell
npm test
```

Build `2026-08-21-door-formula-v2` validates all five JS/JP/JA/JE formula
door-count combinations and verifies that the two counts drive formula weight
and area. Other door products accept only 1/0 and 0/1 and select the matching
database single/double record. Quick quote reads SINGLE for all five approved
JS/JP/JA/JE combinations. Door counts still drive attachment quantities and
BOM output, but do not add an automatic surcharge. Formula totals and their
database template selection remain unchanged. Regression coverage also verifies
that the former JS/JP transformation is an ordinary manually selected attachment.

Manual attachment catalogue input is normalized and validated before the API
generates an idempotent PostgreSQL insert. Automated tests do not connect to or
modify Neon.

Nearest-size SQL contracts select the same-product candidate by perimeter
difference first and scale non-standard material, labor, spray, product-area
inputs and quick face price by input perimeter / matched perimeter. BOM totals
remain cabinet-level values and are deliberately not perimeter-scaled.

## v2026.8.18

- API build `2026-08-26-signed-attachments-v1` retains the existing variant normalization and adds signed installation-board selections with positive source-price snapshots.
- The formula quote card exposes an `人工成本折扣系数` control. Changing it immediately recalculates labor cost, the 6% management fee on material, auxiliary, cabinet labor, confirmed attachment costs, spray and freight, and the formula total from the unmodified database result.
- Draft items persist both the original formula result and the selected labor multiplier, preventing repeated edits from applying the multiplier more than once.
- Client typography and quotation-card sizing were increased for clearer presentation.

## 新建方案的工作区重置（2026-10-19）

- 新建方案使用统一的工作区重置入口，清除选型、公司、图纸及批注、附件、报价行、成本明细、编辑/撤销引用和临时计算结果；保留目录、操作人及系统默认设置（数量 1、板厚 1.5 mm、单/双门 1/0）。不删除已保存方案或本机订单文件。
- 加入报价和报价单生成/导出进度均回到隐藏的空闲状态，清空计时、失败原因、定位按钮及字段的人工/AI 标记；切换页面或缩放窗口不会重建旧提示。
- 旧报价、识图、预检、打开方案请求的延迟返回不能回填新工作区。运行中的 Qt 线程保留至安全结束，不强制终止；正在保存方案或正式导出时须先等待任务完成。
- `tests/verify_new_scheme_workspace_reset.py`：11 项离线实际 Qt 客户端测试，覆盖成功/失败后新建、取消、重复新建、页面切换、延迟回调、旧渲染结果、新报价加入及导出/保存保护。100%、125%、150%、200% 缩放均通过并检查截图。
- 相关回归：方案中心/恢复、普通柜和并柜请求生命周期、暂停重试、复制重新取价、报价单进度、图纸、报价进度、附件导出快照及正式报价共 10 组全部通过。测试不写入线上报价或数据库；本次未重新构建 EXE。
