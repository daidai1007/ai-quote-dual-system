from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import final_attachment_quantity  # noqa: E402
from quick_discount_rules import effective_attachment_quantity  # noqa: E402


def verify(calculator):
    assert calculator(
        {"item_name": "风机", "quantity": 2, "selection_source": "manual"}, 3
    ) == 6
    assert calculator(
        {"item_name": "铜排", "quantity": 2, "selection_source": "manual"}, 3, 4
    ) == 24
    assert calculator(
        {"item_name": "人工附件", "quantity": 2, "selection_source": "QUOTE_LOCAL"}, 3, 4
    ) == 24
    assert calculator(
        {"item_name": "自动附件", "quantity": 8, "selection_source": "automatic"}, 3, 4
    ) == 24
    assert calculator({
        "item_name": "固定底座",
        "quantity": 2,
        "selection_source": "manual",
        "ganged_fixed_base_match": True,
        "ganged_fixed_base_index": 0,
    }, 3, 4) == 6


verify(final_attachment_quantity)
verify(effective_attachment_quantity)
print("manual ganged attachment quantity verified")
