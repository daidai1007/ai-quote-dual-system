"""Side panels match depth before H+D; price ratios still use H/D, never W."""

from __future__ import annotations

import sys
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))

from attachment_category_browser import match_attachment_size  # noqa: E402
from attachment_v2_client import merge_cost, match_catalog_attachment  # noqa: E402
from scheme2_ui import AttachmentEditor, _printable_quote_html  # noqa: E402


def side(identifier: int, width: int, height: int, depth: int, price: float) -> dict:
    return {
        "attachment_price_id": identifier,
        "category_level1": "侧板",
        "item_name": "JP控制柜侧板",
        "width_mm": width,
        "height_mm": height,
        "depth_mm": depth,
        "price": price,
    }


near = side(1, 9999, 1800, 400, 524.593927)
far = side(2, 700, 1600, 420, 500)
for width in (700, 1400):
    matched = match_attachment_size([near, far], far, (width, 1700, 420))
    assert matched is not None
    assert matched["attachment_price_id"] == 2
    assert matched["size_match_target_perimeter"] == 2120
    assert matched["size_match_perimeter"] == 2020
    assert matched["size_match_ratio"] == 2120 / 2020
    assert matched["unit_price_override"] == round(500 * 2120 / 2020, 6)
    merged = merge_cost(
        {**matched, "quantity": 1},
        {"quantity": 1, "quick_amount": 500, "formula_amount": 137.16},
    )
    assert AttachmentEditor._display_amounts(merged) == (137.16, 524.75)

exact = side(3, 9999, 1700, 420, 530)
matched = match_attachment_size([near, exact], near, (700, 1700, 420))
assert matched is not None and matched["attachment_price_id"] == 3
assert matched["size_match_exact"] is True
assert "unit_price_override" not in matched

# Matching perimeter alone must not outrank the correct depth.
wrong_depth = side(4, 700, 1600, 520, 400)  # H+D=2120 exactly.
assert match_attachment_size([wrong_depth, far],far,(700,1700,420))['attachment_price_id']==2
# Without an exact depth, compare depth distance before perimeter distance.
closest_depth = side(5, 1, 2200, 430, 700)
assert match_attachment_size([wrong_depth,closest_depth],wrong_depth,(700,1700,420))['attachment_price_id']==5
# Equal depth (including equal nonzero depth distance): perimeter decides.
same_depth_nearer = side(6, 3, 1800, 420, 550)
assert match_attachment_size([far,same_depth_nearer],far,(700,1750,420))['attachment_price_id']==6
equal_distance = side(7, 1, 1700, 410, 450)
assert match_attachment_size([closest_depth,equal_distance],closest_depth,(700,1700,420))['attachment_price_id']==7
# Deterministic ties and manually selected source price schemes stay intact.
duplicate = side(8, 9999, 1800, 420, 800)
for candidates in ([same_depth_nearer,duplicate],[duplicate,same_depth_nearer]):
    assert match_attachment_size(candidates,far,(700,1750,420))['attachment_price_id']==6
scheme = {**wrong_depth,'attachment_price_id':9,'variant':'指定方案'}
assert match_attachment_size([far,scheme],scheme,(700,1700,420))['attachment_price_id']==9
# Unknown depth is a fallback, not an invented exact-depth catalogue record.
unknown = side(10,700,1700,None,100)
assert match_attachment_size([unknown,closest_depth],unknown,(700,1700,420))['attachment_price_id']==5
assert match_attachment_size([unknown],unknown,(700,1700,420))['attachment_price_id']==10
# A historical automatic model must not bypass the new priority on recalculation.
old = {**wrong_depth,'model_code':'OLD'}
catalog = [old,{**far,'model_code':'NEW'}]
selection={**old,'size_match_target_width_mm':700,'size_match_target_height_mm':1700,'size_match_target_depth_mm':420}
assert match_catalog_attachment(selection,catalog,(700,1700,420),'JP_SINGLE')['attachment_price_id']==2
assert match_catalog_attachment(selection,catalog,(700,1700,520),'JP_SINGLE')['attachment_price_id']==4

panel = {**side(999, 0, 2000, 600, 737.216821), "quick_face_prices_by_material": {"SUS304": 1674}}
for material, expected in (("SECC", 737.216821), ("SUS304", 1674), ("SUS316", 737.216821)):
    match = match_catalog_attachment(panel, [panel], (800, 2000, 600), "JP_SINGLE", material_code=material)
    assert match["attachment_price_id"] == 999 and match["matched_price"] == expected
    assert match["price"] == 737.216821
match = match_catalog_attachment(panel, [panel], (800, 2050, 600), "JP_SINGLE", material_code="SUS304")
assert match["size_match_original_price"] == 1674
assert round(match["unit_price_override"], 2) == 1706.19
source = {**match, "quantity": 2, "quick_amount": 1474.44, "unit_price_override": 737.22,
          "custom_amount_edited": False}
new_price = {"status": "CALCULATED", "quantity": 2, "material_quick_face_price": 1674,
             "quick_price_material_code": "SUS304", "face_price": 1674, "unit_price_override": 1706.19,
             "size_match_ratio": 2650 / 2600, "quick_amount": 3412.38, "formula_amount": 100}
recomputed = merge_cost(source, new_price)
assert AttachmentEditor._display_amounts(recomputed) == (100, 3412.38)
manual = merge_cost({**source, "quick_amount_override": 1200, "custom_amount_edited": True}, new_price)
assert AttachmentEditor._display_amounts(manual) == (100, 1200)
base_price = {"status": "CALCULATED", "quantity": 2, "quick_amount": 1474.44,
              "size_match_exact": True, "size_match_ratio": 1, "formula_amount": 100}
base_again = merge_cost(recomputed, base_price)
assert AttachmentEditor._display_amounts(base_again) == (100, 1474.44)
assert "quick_price_material_code" not in base_again and "unit_price_override" not in base_again

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QFontDatabase, QTextDocument  # noqa: E402
from PySide6.QtPrintSupport import QPrinter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pypdf import PdfReader  # noqa: E402

app = QApplication.instance() or QApplication([])
if Path("C:/Windows/Fonts/msyh.ttc").is_file():
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
window = SimpleNamespace(_quote_order_nature="EXTERNAL")
with TemporaryDirectory() as folder:
    for version, amount in ((1, 1674.44), (2, 3612.38)):
        snapshot = dict(customer="本机测试", scheme_no="LOCAL-JP", quote_date="2026-11-12",
                        quote_version=version, items=[dict(name="JP 控制柜", specification="800×600×2050",
                        quantity=1, unit="台", unit_price=amount, total=amount, remark="侧板2副")])
        output = Path(folder) / f"JP-V{version}.pdf"
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output))
        document = QTextDocument()
        document.setHtml(_printable_quote_html(window, document=snapshot))
        assert f"{amount:,.2f}" in document.toPlainText()
        document.print_(printer)
        extracted = "".join(page.extract_text() for page in PdfReader(output).pages)
        assert f"{amount:,.2f}" in "".join(extracted.split()), repr(extracted)
print("PASS: side-panel sizing, material prices, manual overrides and historical/new PDF output")
