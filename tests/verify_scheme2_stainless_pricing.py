from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
from material_prices import material_unit_price
client = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
quick_sql = (ROOT / "database" / "migrations" / "enforce_quick_quote_dimension_only.sql").read_text(encoding="utf-8")
main = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")

settings = {"carbon_price": 4.2, "stainless_304_price": 18, "stainless_316_price": 36}
assert [material_unit_price(settings, code) for code in ("SECC", "SUS304", "SUS316")] == [4.2, 18, 36]
assert 'updates["material_unit_price_override"] = values["carbon_price"]' in client
assert '"material_code": self.material_combo.currentData()' in main
assert "AND q.material_code=p_material_code" in quick_sql
assert "current_price = material_unit_price(state, selected_code)" in client
assert '"不锈钢304价格"' in client and '"不锈钢316价格"' in client
print("scheme2 stainless material and face-price contract passed")
