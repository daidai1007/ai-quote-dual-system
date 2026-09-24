from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")


def test_quote_preview_consistency_hint_is_removed():
    assert "预览格式与打印、导出报价单保持一致" not in SOURCE
