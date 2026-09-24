from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEME = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
ATTACHMENT = (ROOT / "desktop_client" / "attachment_v2_client.py").read_text(encoding="utf-8")
PREVIEW = (ROOT / "desktop_client" / "quote_drawing_preview.py").read_text(encoding="utf-8")


def test_custom_attachment_skips_catalog_and_is_preserved_for_manual_cost():
    assert 'not item.get("custom") and item.get("attachment_price_id") is None' in SCHEME
    assert 'not item.get("custom") and item.get("attachment_price_id") is None' in ATTACHMENT
    assert 'if source.get("custom"):' in ATTACHMENT
    assert '_v2_custom_attachments' in ATTACHMENT


def test_drawing_toolbar_has_one_clockwise_rotate_button():
    assert "self.rotate_button = self.button('旋转', lambda: self.rotate_page(90), row)" in PREVIEW
    assert "self.button('左转'" not in PREVIEW
    assert "self.button('右转'" not in PREVIEW
