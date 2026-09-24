from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidget, QTableWidgetItem

from desktop_client import scheme2_ui


app = QApplication.instance() or QApplication([])


def test_discounted_unit_price_edit_updates_discount_and_total():
    item = {"quantity": 2, "quick": {"total_cost": 1000}, "formula": {"total_cost": 600}}
    table = QTableWidget(11, 8)
    table.setItem(10, 5, QTableWidgetItem("750.00"))
    window = SimpleNamespace(
        _scheme2_refreshing_quote=False, draft_items=[item], scheme2_quote_preview=table,
        refresh_summary=lambda: None,
    )
    scheme2_ui._quote_unit_price_changed(window, 10, 5)
    assert item["quick_discount"] == 0.75
    assert scheme2_ui._row_values(item)[16] == 1500


def test_print_format_uses_order_date_buyer_seller_and_required_columns():
    item = {
        "name": "未命名", "specification": "1250*400*2000", "quantity": 1,
        "quick": {"total_cost": 4294.83}, "formula": {"total_cost": 3000},
        "final_remark": "既有备注。",
    }
    company = SimpleNamespace(currentText=lambda: "买方公司")
    order = QLineEdit(); order.setText("Q202609231816")
    window = SimpleNamespace(draft_items=[item], scheme2_company=company, scheme2_order_number=order)
    rendered = scheme2_ui._printable_quote_html(window)
    for text in ("Q202609231816", "买方公司", "浙江京能电力设备有限公司", "单价", "总价", "既有备注。"):
        assert text in rendered


def test_quote_table_wraps_full_remarks_and_company_change_refreshes_it():
    source = open(scheme2_ui.__file__, encoding="utf-8").read()
    assert "preview.setWordWrap(True)" in source
    assert "preview.setTextElideMode(Qt.TextElideMode.ElideNone)" in source
    assert "preview.setRowHeight(row, max(72, preview.rowHeight(row)))" in source
    assert "window.scheme2_company.currentTextChanged.connect" in source
