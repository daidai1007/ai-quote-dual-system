"""Offline Qt verification of actual workbench cache and phase progress."""
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop_client'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
import layout_refresh as client
import scheme2_ui as ui
import v3_launcher

app = QApplication.instance() or QApplication([])
ns = v3_launcher.load_v3_namespace()
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns['install_application_font'](app)
ns['MainWindow'].load_catalogs = lambda self: None
ns['AttachmentDialog'].load_catalog = lambda self, *_args: None
original_open = client.urllib.request.urlopen
calls = []


class Response:
    def __init__(self, data, streaming=False):
        self.headers = {'Content-Type': 'application/x-ndjson' if streaming else 'application/json'}
        self.data = io.BytesIO(data)
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return self.data.read()
    def readline(self, limit): return self.data.readline(limit)


def templates(request, timeout=0):
    assert request.full_url.endswith('/api/quotes/formula-template'), 'offline test must never access other endpoints'
    calls.append(json.loads(request.data))
    return Response(json.dumps({'template_version': 'test-v1', 'template': {
        'template_code': 'JP_SINGLE', 'option_cells': {'defaults': {}}, 'rules': [],
    }}).encode())


client.urllib.request.urlopen = templates
window = None
try:
    window = ns['MainWindow']()
    window.resize(1519, 987)
    window.product_catalog = {'JP': {'method': 'formula', 'codes': {'SINGLE': 'JP_SINGLE'}}}
    window.product_combo.blockSignals(True)
    window.product_combo.clear()
    window.product_combo.addItem('JP', 'JP')
    window.product_combo.blockSignals(False)
    window.selected_product_code = lambda: 'JP_SINGLE'
    window.formula_calculator = SimpleNamespace(sheets={'JP_SINGLE': True},
        load_template=lambda _payload: None,
        calculate=lambda _code, width, height, depth, *_doors: (width / 10, height * depth / 1e6))
    client._fetch_formula_template(window.base_url() + '/api/quotes/formula-template', 'JP_SINGLE', ns.get('api_headers'))
    window.width_spin.setValue(1000)
    window.height_spin.setValue(2100)
    window.depth_spin.setValue(600)
    window.refresh_formula_inputs()
    assert float(window.weight_edit.text()) == 100
    window.width_spin.setValue(800)
    window.refresh_formula_inputs()
    assert float(window.weight_edit.text()) == 80
    assert len(calls) == 1, calls
    assert not window._formula_template_debounce_timer.isActive()
    assert getattr(window, 'template_worker', None) is None

    window._scheme2_add_after_calculate = True
    window._scheme2_add_started_at = time.monotonic() - 20
    client._update_calculation_progress(window, {'stage': 'cabinet', 'completed': 0, 'total': 2, 'request_id': 'ui-trace'})
    phase_started = window._scheme2_add_phase_started_at
    client._update_calculation_progress(window, {'stage': 'cabinet', 'completed': 1, 'total': 2, 'request_id': 'ui-trace'})
    assert window._scheme2_add_phase_started_at == phase_started, 'child counts must not reset stage timing'
    assert '1/2' in window.scheme2_add_progress.format()
    assert 'ui-trace' in window.scheme2_add_progress.toolTip()
    client._update_calculation_progress(window, {'stage': 'attachments', 'request_id': 'ui-trace'})
    assert window.scheme2_add_progress.property('step') == 4
    assert window._scheme2_add_phase_started_at >= phase_started
    assert '累计' in window.scheme2_add_progress.toolTip()
    client._update_calculation_progress(window, {'stage': 'snapshot', 'request_id': 'ui-trace'})
    assert window.scheme2_add_progress.property('step') == 5
    assert '保存' in window.scheme2_add_progress.format()

    # The recovered runtime worker class receives an actual progress signal.
    events = [{'type':'progress','stage':'cabinet','completed':0,'total':1,'request_id':'stream-trace'},
              {'type':'progress','stage':'snapshot','request_id':'stream-trace'},
              {'type':'result','result':{'formula_cost':{},'quick_quote':{}}}]
    stream = '\n'.join(json.dumps(event) for event in events).encode() + b'\n'
    client.urllib.request.urlopen = lambda *_args, **_kwargs: Response(stream, True)
    worker = ns['ApiWorker'](window.base_url() + '/api/quotes/calculate-dual', {}, window)
    received, errors = [], []
    worker.succeeded.connect(received.append)
    worker.failed.connect(errors.append)
    worker.start()
    deadline = time.monotonic() + 3
    while worker.isRunning() and time.monotonic() < deadline:
        QTest.qWait(10)
    app.processEvents()
    assert received and not errors, errors
    assert window._quote_progress_request_id == 'stream-trace'
    assert window.scheme2_add_progress.property('step') == 5

    # Render the real footer, using its existing component/theme.
    window.show()
    app.processEvents()
    ui._refresh_add_progress_display(window)
    app.processEvents()
    footer = window.scheme2_add_progress.parentWidget()
    peers = [footer.layout().itemAt(index).widget() for index in range(footer.layout().count())]
    for peer in peers:
        if peer is not window.scheme2_add_progress and not peer.isHidden():
            assert not peer.geometry().intersects(window.scheme2_add_progress.geometry()), 'progress must not overlap footer actions'
    output = ROOT / '.codex-tmp' / 'quote-progress-preview.png'
    window.scheme2_add_progress.parentWidget().grab().save(str(output))
    footer.setFixedWidth(620)
    ui._refresh_add_progress_display(window)
    app.processEvents()
    assert '累计' not in window.scheme2_add_progress.format()
    assert '累计' in window.scheme2_add_progress.toolTip()
    for peer in peers:
        if peer is not window.scheme2_add_progress and not peer.isHidden():
            assert not peer.geometry().intersects(window.scheme2_add_progress.geometry())
    footer.grab().save(str(ROOT / '.codex-tmp' / 'quote-progress-compact-preview.png'))
finally:
    if window is not None:
        for worker in window.findChildren(client.QThread):
            worker.wait(3000)
        window.close()
    client.urllib.request.urlopen = original_open
    client._FORMULA_TEMPLATE_CACHE.clear()

print('PASS: actual Qt workbench reuses template on dimensions, tracks phase/total time and consumes streamed worker progress')
