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


def test_quick_quote_keeps_unlisted_attachment_fee_outside_discount():
    item = {
        "quantity": 1, "quick_discount": 0.75,
        "quick": {"total_cost": 597.92, "attachment_fee": 95},
        "formula": {"total_cost": 400}, "freight_fee": 0,
        "attachments": [
            {"item_name": "接地线-黄绿线", "quantity": 1, "catalog_version": "v2", "quick_amount": 10},
            {"item_name": "铜排", "quantity": 1, "catalog_version": "v2", "quick_amount": 15},
        ],
    }
    # 597.92 - 95 = 502.92 is the discountable cabinet portion;
    # the authoritative 95 attachment/unlisted fee remains at original price.
    assert round(scheme2_ui._row_values(item)[15], 2) == 472.19
    assert round(scheme2_ui._row_values(item)[16], 2) == 472.19
    freight_case = dict(
        item,
        quick={"total_cost": 527.92, "attachment_fee": 25},
        freight_fee=70,
    )
    # With the 70 freight stored separately, the same visible face price is
    # 527.92 + 70 = 597.92; freight remains outside the discount:
    # 502.92 * .75 + 25 + 70 = 472.19.
    assert round(scheme2_ui._row_values(freight_case)[13], 2) == 597.92
    assert round(scheme2_ui._row_values(freight_case)[15], 2) == 472.19


def test_quote_name_edit_updates_the_saved_item_and_rejects_blank_names():
    item = {"name": "未命名", "quantity": 1, "quick": {"total_cost": 100}, "formula": {"total_cost": 60}}
    table = QTableWidget(0, 8)
    window = SimpleNamespace(
        _scheme2_refreshing_quote=False, draft_items=[item], scheme2_quote_preview=table,
        scheme2_company=SimpleNamespace(currentText=lambda: ""),
        scheme2_order_number=QLineEdit(), refresh_summary=lambda: None,
    )
    scheme2_ui._refresh_quote_page(window)
    assert table.item(10, 1).flags() & scheme2_ui.Qt.ItemFlag.ItemIsEditable
    assert not table.item(10, 2).flags() & scheme2_ui.Qt.ItemFlag.ItemIsEditable

    table.item(10, 1).setText("人工名称")
    scheme2_ui._quote_name_changed(window, 10, 1)
    assert item["name"] == "人工名称"

    table.item(10, 1).setText("   ")
    scheme2_ui._quote_name_changed(window, 10, 1)
    assert item["name"] == "人工名称"


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


def test_export_snapshot_freezes_exact_visible_quote_row_without_mutating_draft():
    copper = {
        "item_name": "铜排", "quantity": 1, "catalog_version": "v2",
        "quick_amount": 15, "quick_amount_override": 15,
        "unit_price_override": 15, "custom_amount_edited": True,
    }
    item = {
        "name": "人工名称", "source_pdf_name": "旧图号.pdf",
        "specification": "600*230*400", "quantity": 2, "quick_discount": 0.8,
        "quick": {"total_cost": 560, "attachment_fee": 15, "base_price": 545},
        "formula": {"total_cost": 300},
        "final_remark": "人工备注。", "attachments": [copper],
    }
    table = QTableWidget(0, 8)
    window = SimpleNamespace(
        _scheme2_refreshing_quote=False, draft_items=[item], scheme2_quote_preview=table,
        scheme2_company=SimpleNamespace(currentText=lambda: "买方公司"),
        scheme2_order_number=QLineEdit(), refresh_summary=lambda: None,
    )
    scheme2_ui._refresh_quote_page(window)
    expected = {
        "name": table.item(10, 1).text(),
        "specification": table.item(10, 2).text(),
        "quantity": 2,
        "unit": table.item(10, 4).text(),
        "unit_price": 451.0,
        "discount": 0.8,
        "total": 902.0,
        "remark": table.item(10, 7).text(),
        "attachments": [copper],
        "quick_total_cost": 560,
        "quick_attachment_fee": 15,
        "quick_base_price": 545,
    }

    exported = scheme2_ui._quote_export_items_snapshot(window)

    assert exported[0]["quote_display"] == expected
    assert "quote_display" not in item
    item["name"] = "导出后继续修改"
    assert exported[0]["quote_display"]["name"] == "人工名称"


def test_recovered_core_export_receives_frozen_snapshot_and_restores_live_draft():
    live_item = {
        "name": "柜体",
        "attachments": [{"item_name": "风机", "quick_amount": 51}],
    }
    live_items = [live_item]
    frozen_items = [{
        "name": "柜体",
        "quote_display": {
            "attachments": [{"item_name": "风机", "quick_amount": 60}],
        },
    }]
    seen = []
    window = SimpleNamespace(
        draft_items=live_items,
        quote_export_items_snapshot=lambda: frozen_items,
    )

    def capture_payload():
        seen.append({"items": window.draft_items})
        return "started"

    result = scheme2_ui._call_core_confirm_and_export_with_snapshot(
        window,
        capture_payload,
    )

    assert result == "started"
    assert seen[0]["items"] is frozen_items
    assert seen[0]["items"][0]["quote_display"]["attachments"][0]["quick_amount"] == 60
    assert window.draft_items is live_items
    assert live_items[0]["attachments"][0]["quick_amount"] == 51
