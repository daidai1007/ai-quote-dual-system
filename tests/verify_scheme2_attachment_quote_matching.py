from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_v2_client import match_quote_attachment


class Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class Text:
    def text(self):
        return "800*600*(2000+100)"


window = SimpleNamespace(
    width_spin=Value(800),
    height_spin=Value(2000),
    depth_spin=Value(600),
    quote_spec_edit=Text(),
    ganged_cabinets=[],
    selected_product_code=lambda: "JP",
)
catalog = [
    {"attachment_price_id": 1, "category_level1": "侧板", "item_name": "侧板", "height_mm": 1900, "depth_mm": 600, "price": 19},
    {"attachment_price_id": 2, "category_level1": "侧板", "item_name": "侧板", "height_mm": 2000, "depth_mm": 600, "price": 20},
    {"attachment_price_id": 11, "category_level1": "安装附件", "category_level2": "固定立柱", "item_name": "固定立柱", "height_mm": 1800, "price": 18},
    {"attachment_price_id": 12, "category_level1": "安装附件", "category_level2": "固定立柱", "item_name": "固定立柱", "height_mm": 2000, "price": 20},
    {"attachment_price_id": 21, "category_level1": "底座", "category_level2": "固定底座", "item_name": "固定底座", "width_mm": 800, "height_mm": 100, "depth_mm": 600, "price": 30},
    {"attachment_price_id": 22, "category_level1": "底座", "category_level2": "固定底座", "item_name": "固定底座", "width_mm": 800, "height_mm": 200, "depth_mm": 600, "price": 40},
]

assert match_quote_attachment(window, {"category_level1": "侧板", "item_name": "侧板"}, catalog)["attachment_price_id"] == 2
assert match_quote_attachment(window, {"category_level1": "安装附件", "item_name": "固定立柱"}, catalog)["attachment_price_id"] == 12
assert match_quote_attachment(window, {"category_level1": "底座", "item_name": "固定底座"}, catalog)["attachment_price_id"] == 21

print("PASS: scheme attachment selections retain quick-size matching before database pricing")
