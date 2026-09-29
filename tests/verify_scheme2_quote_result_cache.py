from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

import scheme2_ui

signature = ("JP", 800, 600, 1800, "SECC")
window = SimpleNamespace(
    current_result={"formula": {"total_cost": 100}, "quick": {"total_cost": 120}},
    quote_input_signature=lambda: signature,
)
scheme2_ui._stamp_quote_result_signature(window)
assert window.current_result["input_signature"] == signature
pending_attachments = []
valid = (
    not pending_attachments
    and isinstance(window.current_result, dict)
    and window.current_result.get("input_signature") == window.quote_input_signature()
)
assert valid
print("PASS: unchanged quote inputs reuse the completed API result")
