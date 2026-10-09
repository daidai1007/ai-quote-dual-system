# V3 desktop client overlay

The deployed `AIQuoteDualSystem_layout_v6.exe` uses the recovered CPython 3.12
V3 core, not the legacy `main.py` UI that remains in this public repository.
The source-controlled V3 maintenance layer consists of:

- `v3_launcher.py`: loads the verified V3 core and installs compatibility layers;
- `recognition_repair.py`: preserves the deployed OCR evidence repair;
- `layout_refresh.py`: owns responsive layout, visual tokens, door-count state,
  manual specification parsing, database-driven option presentation, the
  four-column drill-down attachment browser and the persistent
  attachment-catalog entry point.

Quote formulas, quick-quote rules, BOM data and Excel generation remain outside
`layout_refresh.py`. Attachment catalogue writes are sent to the API and are
never stored only in the desktop process.

## Local layout verification

The verified V3 core is a build artifact and is intentionally not committed.
Run the layout contract with the same Python 3.12/PySide6 environment used by
the client:

```powershell
$env:AI_QUOTE_V3_CORE_ROOT='G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem\_internal\v3_core'
$env:AI_QUOTE_UI_ARTIFACT_DIR='<optional screenshot output directory>'
python tests\verify_v3_layout_refresh.py
```

The contract runs offline: it disables catalog loading before creating the
window, so it does not call Render or Neon.

## 报价性能与进度（2026-10-09）

- 公式模板按 API 地址、认证范围、产品和内容版本缓存在进程内，最多 64 项。修改尺寸时直接复用有效模板；30 秒校验窗口到期后，下次使用会向 API 校验版本。内容未变化时只返回版本标记；公式、规则或映射变化后返回新模板。校验失败不使用过期模板报价，旧 API 不提供版本时不启用此缓存。
- 并柜使用 `POST /api/quotes/calculate-ganged` 一次提交 2–20 个子柜。服务端限制为 2 个子柜同时计算，并在同一批次内合并相同规则/价格查询。子柜基础计算回滚临时数据库写入，最终只保存一次并柜附件快照。新报价不会复用上一批次的价格；原有固定底座和附件数量规则不变。
- 客户端请求 `Accept: application/x-ndjson`，API 依次发送真实阶段进度和最终结果。没有该请求头的旧客户端仍收到普通 JSON；仅当批量接口返回 404/405 时回退到旧逐柜接口，计算失败不会自动重复提交。
- 底部进度区显示当前阶段时间，宽屏同时显示累计时间；窄屏显示简短阶段，悬停可查看完整时间和请求编号。子柜完成计数更新不会重置阶段计时。
- 客户端日志在 `%LOCALAPPDATA%/AIQuoteDualSystem/logs/client.log`。服务端日志记录请求编号、各子柜、材料/辅材/人工/喷涂阶段、数据库耗时及批次查询复用；不记录 SQL、请求正文、API 密钥或数据库连接串。

专项验证：`npm run test:performance`、`npm run test:database:performance`（后者仅用于本机 55439 隔离测试库），以及 `tests/verify_template_cache_and_batch.py`、`tests/verify_quote_progress_ui.py`。上线需要先部署 API，再重新构建客户端；无需新增数据库迁移。
