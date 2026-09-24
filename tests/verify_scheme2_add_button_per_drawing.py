from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")


def test_add_button_text_is_synchronized_from_current_drawing_quote_state():
    assert "def _sync_scheme2_add_action(window, quoted):" in SOURCE
    assert 'add_button.setText("已加入" if quoted else "加入报价清单")' in SOURCE
    badge_sync = SOURCE[SOURCE.index("def _sync_scheme2_quoted_badge"):SOURCE.index("def _sync_scheme2_page_navigation")]
    assert "_sync_scheme2_add_action(window, quoted)" in badge_sync
