from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
client = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
quick_sql = (ROOT / "database" / "migrations" / "enforce_quick_quote_dimension_only.sql").read_text(encoding="utf-8")
main = (ROOT / "desktop_client" / "main.py").read_text(encoding="utf-8")

assert 'if material_code not in {"SUS304", "SUS316"}' in client
assert 'updates["material_unit_price_override"] = values["carbon_price"]' in client
assert '"material_code": self.material_combo.currentData()' in main
assert "AND q.material_code=p_material_code" in quick_sql
assert "state.get(\"stainless_price\") if selected_code in {\"SUS304\", \"SUS316\"}" in client
print("scheme2 stainless material and face-price contract passed")
