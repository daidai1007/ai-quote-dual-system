# V3 desktop client overlay

The deployed `AIQuoteDualSystem_layout_v6.exe` uses the recovered CPython 3.12
V3 core, not the legacy `main.py` UI that remains in this public repository.
The source-controlled V3 maintenance layer consists of:

- `v3_launcher.py`: loads the verified V3 core and installs compatibility layers;
- `recognition_repair.py`: preserves the deployed OCR evidence repair;
- `layout_refresh.py`: owns responsive layout, visual tokens and UI state feedback.

Quote formulas, quick-quote rules, attachment pricing, BOM data, database writes
and Excel generation remain outside `layout_refresh.py`.

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
