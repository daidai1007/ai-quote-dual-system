from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "desktop_client" / "scheme2_ui.py").read_text(encoding="utf-8")
API = (ROOT / "api" / "server.mjs").read_text(encoding="utf-8")
SQL = (ROOT / "database" / "migrations" / "order_workspace.sql").read_text(encoding="utf-8")


def test_cost_hint_removed_and_navigation_fonts_increased():
    assert "运费、数量可直接编辑；点击产品可批量设置同型号折扣" not in UI
    assert "QLabel#scheme2ServiceStatus" in UI and "font-size:11px" in UI
    assert "QFrame#navPanel QPushButton" in UI and "font-size:13px" in UI


def test_requested_option_labels_share_door_heading_style():
    assert 'product_field = _option_field(window, "产品", product)' in UI
    assert '_promote_option_label(product_field)' in UI
    assert '_promote_option_label(quantity_field)' in UI
    assert '_promote_option_label(thickness_field)' in UI
    assert 'attachment_title.setObjectName("scheme2OptionGroupTitle")' in UI


def test_order_number_restores_and_saves_all_three_page_data_online():
    assert 'order_number.setPlaceholderText("请输入订单号")' in UI
    assert '_promote_option_label(order_field)' in UI
    assert '"option_state": _capture_scheme2_page_state(window)' in UI
    assert '"draft_items": deepcopy(getattr(window, "draft_items", []))' in UI
    assert '"company": window.scheme2_company.currentText()' in UI
    assert '"active_route": int(window.stack.currentIndex())' in UI
    assert '"detail_item_index": detail_index' in UI
    assert 'order_load_timer.setInterval(500)' in UI
    assert 'order_number.textEdited.connect(lambda _text: order_load_timer.start())' in UI
    assert '"已从本机恢复订单进度及图纸"' in UI
    assert '"订单进度已恢复并同步到本机"' in UI
    assert 'window.show_section(route if route in (OPTION_ROUTE, COST_ROUTE, QUOTE_ROUTE)' in UI
    assert '_show_detail(window, window.draft_items[detail_index])' in UI
    assert '_save_order_workspace(window, lambda _success: window.close())' in UI
    assert 'def _manual_save_order_workspace(window):' in UI
    assert 'save_button.setObjectName("scheme2SaveButton")' in UI
    assert 'save_button.clicked.connect(lambda: _manual_save_order_workspace(window))' in UI
    assert '"/api/orders/workspace/load"' in UI
    assert '"/api/orders/workspace/save"' in UI
    assert "/api/orders/workspace/load" in API
    assert "/api/orders/workspace/save" in API
    assert "calc.client_order_workspace" in SQL


def test_local_order_fallback_archives_and_restores_drawing(tmp_path, monkeypatch):
    from desktop_client import scheme2_ui

    source = tmp_path / "drawing.png"
    source.write_bytes(b"drawing-content")
    cache = tmp_path / "cache"
    monkeypatch.setenv("AI_QUOTE_ORDER_CACHE_ROOT", str(cache))
    payload = {
        "drawing_pages": [{
            "key": f"{str(source).casefold()}#page=1",
            "source_path": str(source), "page_index": 0, "page_count": 1,
        }],
        "draft_items": [],
    }
    saved = scheme2_ui._save_local_order_workspace("123", payload)
    stored = Path(saved["drawing_pages"][0]["source_path"])
    assert stored.is_file() and stored.read_bytes() == b"drawing-content"
    assert stored != source
    assert scheme2_ui._load_local_order_workspace("123") == saved
