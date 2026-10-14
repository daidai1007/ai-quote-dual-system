"""Targeted regression checks for draft edit dimension re-matching."""

from types import SimpleNamespace

import attachment_v2_client as v2


class _Spin:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


def _window(width, height, depth, attachments):
    return SimpleNamespace(
        width_spin=_Spin(width),
        height_spin=_Spin(height),
        depth_spin=_Spin(depth),
        attachments=attachments,
        selected_product_code=lambda: "JP",
    )


def _row(price_id, model, width, height, depth, price):
    return {
        "attachment_price_id": price_id,
        "category_level1": "安装附件",
        "category_level2": "固定立柱",
        "item_name": "固定立柱",
        "model_code": model,
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": price,
        "face_price": price,
    }


def test_changed_dimensions_force_new_size_match_even_with_old_model_id():
    old = _row(101, "OLD", 1000, 1800, 600, 100)
    new = _row(102, "NEW", 1200, 2000, 800, 200)
    source = {
        **old,
        "quantity": 1,
        "size_match_target_width_mm": 1000,
        "size_match_target_height_mm": 1800,
        "size_match_target_depth_mm": 600,
        "size_match_original_price": 100,
        "size_match_ratio": 1,
        "unit_price_override": 100,
    }
    window = _window(1200, 2000, 800, [source])

    assert v2.needs_size_match_resolution(window)
    matched = v2.match_quote_attachment(window, source, [old, new])
    assert matched["attachment_price_id"] == 102
    resolved = v2.resolve_size_matched_attachment(source, matched, "test-v2")
    assert resolved["attachment_price_id"] == 102
    assert resolved["model_code"] == "NEW"
    assert "unit_price_override" not in resolved


def test_dimension_rematch_keeps_manual_amount_override():
    old = _row(101, "OLD", 1000, 1800, 600, 100)
    new = _row(102, "NEW", 1200, 2000, 800, 200)
    source = {
        **old,
        "quantity": 1,
        "size_match_target_width_mm": 1000,
        "size_match_target_height_mm": 1800,
        "size_match_target_depth_mm": 600,
        "unit_price_override": 77,
        "quick_amount_override": 77,
        "quick_amount": 77,
        "custom_amount_edited": True,
    }
    matched = v2.match_quote_attachment(_window(1200, 2000, 800, [source]), source, [old, new])
    resolved = v2.resolve_size_matched_attachment(source, matched, "test-v2")
    assert resolved["attachment_price_id"] == 102
    assert resolved["unit_price_override"] == 77
    assert resolved["quick_amount_override"] == 77
    assert resolved["quick_amount"] == 77


if __name__ == "__main__":
    test_changed_dimensions_force_new_size_match_even_with_old_model_id()
    test_dimension_rematch_keeps_manual_amount_override()
    print("attachment dimension rematch checks passed")
