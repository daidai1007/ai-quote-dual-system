"""Offline runtime contract for the server-backed quote scheme centre."""

from __future__ import annotations
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QAbstractItemView  # noqa: E402
from PySide6.QtCore import QRect, QThread  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
import quote_scheme_center  # noqa: E402
import scheme2_ui  # noqa: E402
import v3_launcher  # noqa: E402

namespace = v3_launcher.load_v3_namespace()
namespace["MainWindow"].load_catalogs = lambda self: None
app = QApplication.instance() or QApplication([])
namespace["install_application_font"](app)
# Keep the synthetic offscreen desktop large enough at 125/150/200% DPI.
work_area = Mock(wraps=app.primaryScreen())
work_area.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
screen_override = patch.object(namespace["MainWindow"], "screen", return_value=work_area)
screen_override.start()
window = namespace["MainWindow"]()
window.show(); app.processEvents()
scheme2_ui._set_nav_collapsed(window, False, manual=True)
app.processEvents()
assert not hasattr(window, "scheme2_diagnostic_button")

# No idle quotation-scheme hint (or blank label space) in the sidebar.
assert window.quote_scheme_save_status.text() == ""
assert window.quote_scheme_save_status.isHidden()
assert not any(label.isVisibleTo(window) and label.text() == "未打开报价方案"
               for label in window.findChildren(QLabel))
quote_scheme_center._set_state(window, "正在创建草稿并生成方案编号…", "busy")
assert window.quote_scheme_save_status.isVisibleTo(window)
quote_scheme_center._set_state(window, "草稿创建失败：离线回归测试", "error")
assert window.quote_scheme_save_status.isVisibleTo(window)
assert window.quote_scheme_page_status.text() == "草稿创建失败：离线回归测试"
quote_scheme_center._new_scheme(window)
assert window.quote_scheme_save_status.isHidden()
assert "首次加入报价清单" in window.quote_scheme_page_status.text()

assert window.windowTitle().endswith(quote_scheme_center.CLIENT_VERSION)
assert window.quote_scheme_nav_button.text() == "报价方案"
assert [button.text() for button in window.nav_buttons] == ["选型配置", "成本计算", "报价单", "报价方案", "报价分析"]
assert window.stack.widget(quote_scheme_center.SCHEME_ROUTE).objectName() == "quoteSchemeCenterPage"
assert window.quote_scheme_page_status is not None
assert window.findChild(QLabel, "quoteSchemeServerNotice").text() == "数据保存于服务器"
assert window.quote_scheme_operator_name.objectName() == "quoteSchemeOperatorName"
assert "自填" in window.quote_scheme_operator_name.toolTip()
assert [window.quote_scheme_table.horizontalHeaderItem(i).text() for i in range(9)] == [
    "方案编号", "客户", "产品", "状态", "报价金额", "创建人", "审核人", "更新时间", "操作",
]
assert {"scheme_no", "company", "product", "creator", "updated_from", "updated_to"} == set(window.quote_scheme_filters)
scheme_page = window.stack.widget(quote_scheme_center.SCHEME_ROUTE)
assert not any(button.text() == "删除" for button in scheme_page.findChildren(QPushButton))

# All filter actions share the existing primary-button style and equal sizing;
# visual unification must not change any of their three signal handlers.
action_buttons = {button.text(): button for button in scheme_page.findChildren(QPushButton)
                  if button.text() in ("查询", "重置", "新建方案")}
assert set(action_buttons) == {"查询", "重置", "新建方案"}
buttons = list(action_buttons.values())
assert all(button.objectName() == "scheme2PrimaryAction" for button in buttons)
assert all(button.font() == buttons[0].font() for button in buttons)
assert len({button.minimumWidth() for button in buttons}) == 1
with patch.object(quote_scheme_center, "_load_list") as load_list, \
        patch.object(quote_scheme_center, "_reset_filters") as reset_filters, \
        patch.object(quote_scheme_center, "_new_scheme") as new_scheme:
    window.show_section(quote_scheme_center.SCHEME_ROUTE)
    app.processEvents()
    load_list.assert_called_once_with(window, 1)
    load_list.reset_mock()
    assert len({button.height() for button in buttons}) == 1
    assert max(button.width() for button in buttons) - min(button.width() for button in buttons) <= 1
    assert all(button.isVisibleTo(window) for button in buttons)
    backgrounds = [button.grab().toImage().pixelColor(12, button.height() // 2).name()
                   for button in buttons]
    assert backgrounds == ["#2563eb"] * 3, backgrounds
    artifact_directory = os.environ.get("AI_QUOTE_UI_ARTIFACT_DIR", "").strip()
    if artifact_directory:
        output = Path(artifact_directory)
        output.mkdir(parents=True, exist_ok=True)
        bounds = buttons[0].geometry()
        for button in buttons[1:]:
            bounds = bounds.united(button.geometry())
        assert buttons[0].parentWidget().grab(bounds).save(str(output / "quote_scheme_actions.png"))
    action_buttons["查询"].click()
    action_buttons["重置"].click()
    action_buttons["新建方案"].click()
    load_list.assert_called_once_with(window, 1)
    reset_filters.assert_called_once_with(window)
    new_scheme.assert_called_once_with(window)
window.show_section(1)

window._quote_scheme_id = "BJ-20261016-000123"
window._quote_scheme_status = "QUOTED"
quote_scheme_center._set_state(window, "BJ-20261016-000123 · 已保存", "ok")
assert window.quote_scheme_save_status.isVisibleTo(window)
assert window.quote_scheme_save_status.text() == window.quote_scheme_page_status.text()
quote_scheme_center._apply_read_only(window, True)
assert not window.scheme2_add_button.isEnabled()
assert window.summary_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
assert window.scheme2_quote_preview.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
if window.scheme2_attachment_button is not None:
    assert not window.scheme2_attachment_button.isEnabled()
quote_scheme_center._apply_read_only(window, False)
assert window.scheme2_add_button.isEnabled()

# Offscreen Qt exposes an 800px desktop. Supply only work-area geometry so
# the real screen-fit logic can exercise these requested logical sizes.
screen = Mock(wraps=window.screen())
screen.availableGeometry.return_value = QRect(0, 0, 4096, 2160)
with patch.object(window, "screen", return_value=screen), \
        patch.object(quote_scheme_center, "_load_list"):
    window.show_section(quote_scheme_center.SCHEME_ROUTE)
    for width, height in ((1024, 700), (1280, 800), (1536, 900)):
        window.resize(width, height)
        QTest.qWait(50)
        assert window.width() == width and window.height() == height
        assert window.quote_scheme_table.width() > 600
        assert window.quote_scheme_table.height() > 200
        assert len({button.height() for button in buttons}) == 1
        assert max(button.width() for button in buttons) - min(button.width() for button in buttons) <= 1
        for button in buttons:
            assert button.fontMetrics().horizontalAdvance(button.text()) < button.width(), (
                width, height, button.text(), button.width(), button.minimumWidth(),
                button.sizeHint().width(), button.fontMetrics().horizontalAdvance(button.text()),
            )
window.show_section(1)

# Merely entering configuration never allocates a number.  The first real
# quote row calls the server, and repeating the hook keeps that same number.
window._quote_scheme_id = ""; window.draft_items = []
quote_scheme_center._ensure_created(window)
assert window._quote_scheme_id == ""
window.quote_scheme_operator_name.setText("张师傅")
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
assert calls[0][2]["operator_name"] == "张师傅"
assert "scheme_summary" in calls[0][2]["snapshot"]
assert calls[0][2]["snapshot"]["document"]["client_version"] == quote_scheme_center.CLIENT_VERSION

# A change made while one save is in flight is not lost: finishing the older
# request schedules another save for the newer dirty sequence.
resaves = []
original_save = quote_scheme_center._save
quote_scheme_center._save = lambda owner: resaves.append(owner._quote_scheme_dirty_seq)
in_flight = object()
window._quote_scheme_save_worker = in_flight
window._quote_scheme_dirty_seq = 2
window._quote_scheme_saved_seq = 0
window._quote_scheme_save_pending = True
window._quote_scheme_last_save_failed = False
quote_scheme_center._save_finished(window, in_flight, window._quote_scheme_id, 1)
app.processEvents()
quote_scheme_center._save = original_save
assert resaves == [2]

# Historical documents retain their frozen scheme number and quote date.
from scheme2_ui import _printable_quote_html  # noqa: E402
window._quote_scheme_quote_date = "2026-10-10"
printed = _printable_quote_html(window)
assert "BJ-20261016-000123" in printed
assert "2026-10-10" in printed

window._quote_scheme_save_timer.stop()
window._quote_scheme_id = ""
window._quote_scheme_create_worker = None
window._quote_scheme_save_worker = None
window._quote_scheme_last_save_failed = False
window._quote_scheme_dirty_seq = window._quote_scheme_saved_seq = 0
window.close()
screen_override.stop()
print("QUOTE_SCHEME_CENTER=PASS")
