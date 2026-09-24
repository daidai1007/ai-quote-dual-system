from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from scheme2_ui import _scheme2_quote_remark

item = {
    "scheme2_selected_product_code": "JP_SINGLE",
    "scheme2_selected_product_name": "JP",
    "scheme2_selected_material": "镀锌板（SECC）",
    "scheme2_selected_surface": "橘纹喷塑",
    "material_code": "SECC",
    "coating_type": "橘纹",
    "display_color": "RAL7035",
    "attachments": [
        {"item_name": "固定立柱"},
        {"item_name": "接地线-黄绿线"},
        {"category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关", "model_code": "24V-0.6m"},
    ],
}
remark = _scheme2_quote_remark(item)
assert remark == "仿威图JP柜，镀锌板（SECC），橘纹喷塑，RAL7035，固定立柱、接地线-黄绿线、照明灯/行程开关（24V-0.6m）。"
assert "仿威图（JP）柜" not in remark and "仿威图(JP)柜" not in remark

item["attachments"] = []
assert _scheme2_quote_remark(item).endswith("，无附件。")
print("scheme2 quote remark contract passed")
