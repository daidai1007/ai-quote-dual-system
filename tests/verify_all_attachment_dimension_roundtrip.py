from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_v2_client import (  # noqa: E402
    confirmation_attachments_for_item,
    confirmation_inputs,
    confirmation_payload,
    merge_cost,
    restore_confirmation_inputs,
    selected_input,
)


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
        # The visible cabinet has a base, so the caller supplies this value to
        # every merge.  Only rules that actually use 底座高度 may retain it.
        automatic_base = 100.0
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
        # The recovered core is allowed to decorate/copy attachment rows, but
        # even an accidental mutation of a compared field must be repaired
        # from the successful server result before confirmation/export.
        mutated = {
            **copy.deepcopy(saved),
            "quantity": 99,
            "attachment_price_sign": -1,
            "manual_inputs": {},
        }
        restored = restore_confirmation_inputs(
            [mutated], confirmation_inputs([request])
        )[0]
        assert confirmation_input(restored) == confirmation_input(request)
        verified += 1

assert verified == 226

# Quote-screen/display logic may decorate or even accidentally overwrite the
# visible attachment fields after pricing.  Confirmation must still submit the
# immutable selection that produced the server quote-line snapshot, while
# retaining quote-local custom rows.
frozen = [{
    "attachment_price_id": 34,
    "quantity": 1,
    "attachment_price_sign": 1,
    "manual_inputs": {},
}]
display_row = {
    **frozen[0],
    "quantity": 2,
    "item_name": "接地线-编织带",
    "final_quantity": 2,
}
custom_row = {
    "custom": True,
    "item_name": "人工附件",
    "quantity": 3,
    "unit_price_override": 5,
}
quote_item = {
    "attachment_contract": 2,
    "attachments": [display_row, custom_row],
    "attachment_confirmation_inputs": frozen,
}
confirmed = confirmation_attachments_for_item(quote_item)
assert confirmed == [frozen[0], custom_row]
payload = {"items": [quote_item], "company_name": "测试公司"}
adapted = confirmation_payload(payload)
assert adapted["items"][0]["attachments"] == [frozen[0], custom_row]
assert payload["items"][0]["attachments"][0]["quantity"] == 2

# Also cover all catalogue rows without manual dimensions: a cabinet base
# must never leak into unrelated attachment inputs such as lamps and fans.
for item in fixture["catalog"]["items"]:
    source = {
        **copy.deepcopy(item),
        "manual_inputs": {},
        "quantity": 1,
        "attachment_price_sign": 1,
    }
    request = selected_input(source, 100.0)
    cost = {
        **copy.deepcopy(source),
        "manual_inputs": copy.deepcopy(request["manual_inputs"]),
        "status": "QUICK_ONLY",
    }
    saved = merge_cost(source, cost, 100.0)
    assert confirmation_input(saved) == confirmation_input(request), (
        item.get("attachment_price_id"),
        item.get("item_name"),
    )

print("all 226 catalog attachments and 113 dimension rules passed snapshot roundtrip")
