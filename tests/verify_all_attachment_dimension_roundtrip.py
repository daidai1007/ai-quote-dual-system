from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_v2_client import merge_cost, selected_input  # noqa: E402


fixture = json.loads(
    (ROOT / "test-output" / "attachment-cost-v2" / "api-client-fixtures.json")
    .read_text(encoding="utf-8")
)

DIMENSIONS_BY_ITEM = {
    "分段板": ("分段板高度",),
    "固定底座": ("底座高度",),
    "活动底座": ("底座高度",),
    "玻璃门": ("玻璃门高度", "玻璃门宽度"),
    "无孔承板": ("孔承板高度", "孔承板宽度"),
    "有孔承板": ("孔承板高度", "孔承板宽度"),
    "通风顶罩": ("通风顶罩高度",),
    "外部眉头(柜体顶板上方)": ("眉头高度",),
    "侧门": ("侧门高度", "侧门宽度"),
}


def confirmation_input(row):
    """Mirror the fields compared by attachment_service.attachmentInput."""

    result = {
        "attachment_price_id": int(row["attachment_price_id"]),
        "quantity": row.get("quantity", 1),
        "attachment_price_sign": row.get("attachment_price_sign", 1),
        "manual_inputs": copy.deepcopy(row.get("manual_inputs") or {}),
    }
    index = row.get("ganged_cabinet_index", row.get("ganged_fixed_base_index"))
    if index is not None:
        result["ganged_cabinet_index"] = int(index)
    return result


parameterized = []
for item in fixture["catalog"]["items"]:
    names = DIMENSIONS_BY_ITEM.get(str(item.get("item_name") or ""), ())
    for rule in item.get("rules") or []:
        formulas = json.dumps(rule.get("formulas") or {}, ensure_ascii=False)
        if names and all(name in formulas for name in names):
            parameterized.append((item, rule, names))

assert len(parameterized) == 113
assert {name for _item, _rule, names in parameterized for name in names} == {
    "分段板高度",
    "底座高度",
    "玻璃门高度",
    "玻璃门宽度",
    "孔承板高度",
    "孔承板宽度",
    "通风顶罩高度",
    "眉头高度",
    "侧门高度",
    "侧门宽度",
}

verified = 0
for item, rule, names in parameterized:
    manual = {name: float(100 + index * 10) for index, name in enumerate(names)}
    required = [
        {"name": name, "source": "MANUAL", "unit": "mm", "required": True}
        for name in names
    ]
    for ganged_index in (None, 1):
        source = {
            **copy.deepcopy(item),
            "required_parameters": required,
            "formulas": copy.deepcopy(rule.get("formulas") or {}),
            "manual_inputs": copy.deepcopy(manual),
            "quantity": 2,
            "attachment_price_sign": 1,
        }
        if ganged_index is not None:
            source["ganged_cabinet_index"] = ganged_index
        automatic_base = 100.0 if "底座高度" in names else None
        request = selected_input(source, automatic_base)
        cost = {
            **copy.deepcopy(source),
            "manual_inputs": copy.deepcopy(request["manual_inputs"]),
            "status": "CALCULATED",
            "formula_unit_cost": 1,
            "formula_amount": 2,
        }
        saved = merge_cost(source, cost, automatic_base)
        assert confirmation_input(saved) == confirmation_input(request), (
            item.get("attachment_price_id"),
            item.get("item_name"),
            names,
            ganged_index,
        )
        verified += 1

assert verified == 226
print("all 113 parameterized attachment rules passed ordinary/ganged roundtrip")
