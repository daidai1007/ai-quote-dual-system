"""Offline runtime contract for the server-backed quote scheme centre."""

from __future__ import annotations
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402
from PySide6.QtCore import QThread  # noqa: E402
import quote_scheme_center  # noqa: E402
import v3_launcher  # noqa: E402

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
window = namespace["MainWindow"]()
window.show(); app.processEvents()

assert window.windowTitle().endswith("2026.10.16.01")
assert window.quote_scheme_nav_button.text() == "报价方案"
assert window.stack.widget(quote_scheme_center.SCHEME_ROUTE).objectName() == "quoteSchemeCenterPage"
assert window.quote_scheme_page_status is not None
assert window.findChild(QLabel, "quoteSchemeServerNotice").text() == "● 数据保存于服务器"
assert [window.quote_scheme_table.horizontalHeaderItem(i).text() for i in range(9)] == [
    "方案编号", "下单公司", "产品/规格摘要", "状态", "报价金额", "创建人", "最后修改人", "更新时间", "操作",
]
assert {"scheme_no", "company", "product", "creator", "updated_from", "updated_to"} == set(window.quote_scheme_filters)
scheme_page = window.stack.widget(quote_scheme_center.SCHEME_ROUTE)
assert not any(button.text() == "删除" for button in scheme_page.findChildren(QPushButton))

window._quote_scheme_id = "BJ-20261016-000123"
window._quote_scheme_status = "QUOTED"
quote_scheme_center._apply_read_only(window, True)
assert not window.scheme2_add_button.isEnabled()
quote_scheme_center._apply_read_only(window, False)
assert window.scheme2_add_button.isEnabled()

for width, height in ((1024, 700), (1280, 800), (1536, 900)):
    window.resize(width, height); app.processEvents()
    assert window.quote_scheme_table.width() > 600
    assert window.quote_scheme_table.height() > 200

# Merely entering configuration never allocates a number.  The first real
# quote row calls the server, and repeating the hook keeps that same number.
window._quote_scheme_id = ""; window.draft_items = []
quote_scheme_center._ensure_created(window)
assert window._quote_scheme_id == ""
calls = []
original_run = quote_scheme_center._run
def fake_run(owner, method, path, payload, success, failure=None):
    calls.append((method, path, payload))
    success({"scheme_no":"BJ-20261016-000123", "status":"DRAFT", "lock_version":1})
    return QThread(owner)
quote_scheme_center._run = fake_run
window.draft_items = [{"product_code":"AE", "quoted_total":100}]
quote_scheme_center._ensure_created(window)
quote_scheme_center._ensure_created(window)
quote_scheme_center._run = original_run
assert window._quote_scheme_id == "BJ-20261016-000123" and len(calls) == 1

window.close()
print("QUOTE_SCHEME_CENTER=PASS")
