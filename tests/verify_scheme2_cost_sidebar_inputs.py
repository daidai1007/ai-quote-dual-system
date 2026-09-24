from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")


def test_sidebar_title_has_no_white_box():
    rule = SOURCE[SOURCE.index("QLabel#scheme2SidebarTitle {"):].split("}", 1)[0]
    assert "background:transparent" in rule
    assert "background:#FFFFFF" not in rule
    assert "border-radius" not in rule


def test_sidebar_price_boxes_are_taller_and_vertically_centered():
    assert "control.setFixedHeight(36)" in SOURCE
    rule = SOURCE[SOURCE.index("QFrame#scheme2CostSidebar QDoubleSpinBox {"):].split("}", 1)[0]
    assert "min-height:28px" in rule
    assert "padding:1px 22px 1px 7px" in rule
