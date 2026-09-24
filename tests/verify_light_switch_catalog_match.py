from desktop_client.attachment_category_browser import match_default_light_switch
from desktop_client.attachment_v2_client import match_catalog_attachment


CATALOG = [
    {"attachment_price_id": 1, "category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关", "model_code": "220V"},
    {"attachment_price_id": 2, "category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关", "model_code": "24V-0.28m"},
    {"attachment_price_id": 3, "category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关", "model_code": "24V-0.6m"},
]


def test_category_only_light_switch_selection_uses_unique_220v_default():
    selection = {"category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关"}
    assert match_catalog_attachment(selection, CATALOG)["attachment_price_id"] == 1
    assert match_default_light_switch(CATALOG)["attachment_price_id"] == 1


def test_explicit_light_switch_model_remains_exact():
    selection = {
        "category_level1": "照明灯/行程开关", "item_name": "照明灯/行程开关",
        "model_code": "24V-0.6m",
    }
    assert match_catalog_attachment(selection, CATALOG)["attachment_price_id"] == 3
