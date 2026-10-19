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

## 统一绿色进度条（2026-10-19）

- 所有进度填充统一使用 `progress_style.PROGRESS_COLORS['fill']`（`#97C459`），覆盖加入报价、生成报价单、导出、识图控制器及动态弹窗；移除失败时切换红色和文档进度使用蓝色的分支。
- 不改变进度范围、计时、延迟显示/自动收起、暂停重试、失败详情和定位按钮；失败状态仍由明确的文字及操作提示表达。已隐藏的旧识图进度控件仍保持隐藏。
- `tests/verify_progress_style.py` 验证实际 Qt 绘制颜色、失败/暂停/完成状态、禁用控件、动态 `QProgressDialog`、重复安装和窗口缩放；配合报价文档反馈及工作区重置回归，防止只修改单个页面。

## 附件汇总的柜体匹配尺寸（2026-10-19）

- “产品报价”在“原价总价”和“柜体”之间新增只读“匹配尺寸”列。使用本次报价 `quick.matched_experience` 中实际命中的目录尺寸，按宽*深*高（mm）显示，不重新查询数据库或推测输入尺寸，不改动原有匹配及价格计算规则。
- 精确匹配也显示命中尺寸；并柜从已保存的子柜匹配列表逐柜显示，保留顺序、重复尺寸和缺失记录（—）。旧订单没有有效匹配快照时显示 —，不冒用输入规格。附件人工改价、原价/折后合计不受影响。
- 自动调整多行高度，保留完整尺寸提示；汇总打印同步包含匹配尺寸，支持宽表分栏、纵横纸张和整行分页。
- `tests/verify_attachment_summary_matched_size.py`：7 项离线实际 Qt 测试，在 100%、125%、150%、200% 缩放下均通过；覆盖近似/精确匹配、尺寸顺序与精度、无效/旧快照、并柜、快照序列化、只读列、附件改价和窗口缩放，并检查截图。另通过汇总布局、单价传播和 5 项打印测试。相关脚本已加入默认客户端测试清单。
- 本次仅修改客户端源码与测试，不修改线上数据库，不重新部署 API，未重新构建或覆盖 EXE。

## 成本明细导出 Excel（2026-10-19）

- 成本明细页顶部新增“导出 Excel”，由保存对话框选择 `.xlsx` 位置。导出当前产品信息、完整 11 列、滚动区域的所有行与合计，保留当前人工系数及调整后金额。小窗口暂时收起的明细列也完整导出，不遗漏规格、公式和备注。
- 直接冻结当前 Qt 表格，不重算价格、不读取数据库、不调用正式报价确认/导出、不修改附件人工数据。写入数值单元格并保持界面显示精度；公式说明和以 `=` 开头的名称为文本，防止误执行。
- 使用标准库生成 OOXML，沿用蓝色表头、交替行底色、换行、合计强调，冻结表头及标识列，设置横向打印及重复表头；无需额外安装 Excel、Node 或 Python 包。同目录唯一临时文件写入后原子替换，失败保留原文件并提示关闭占用文件后重试。
- `tests/verify_cost_detail_export.py` 的 11 项测试覆盖字段逐格一致、正在编辑/零系数、未编辑的四位系数不被导出操作舍入、负数与精度、文字公式、取消、文件占用和替换失败、补扩展名的覆盖确认、订单切换、并柜子柜及整套附件、窗口缩放及按钮。100%、125%、150%、200% 缩放下通过。加入默认客户端测试和打包模块核对清单。
- 独立表格引擎成功读取测试导出文件，核对 11 列、26 行、286 个数据单元格，并渲染检查。零系数、并柜成本明细、6% 管理费、附件导出快照及新建方案清空相关回归通过；仅修改源码，未构建/覆盖当前 EXE。
