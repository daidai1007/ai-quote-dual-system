"""Focused real-window thickness selection, persistence and invalidation checks."""
import os
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop_client'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
import layout_refresh as layout
import scheme2_ui as ui
import v3_launcher

app=QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
ns=v3_launcher.load_v3_namespace()
ns['install_application_font'](app)
Window=ns['MainWindow']
Window.load_catalogs=lambda self:None
Window.refresh_formula_inputs=lambda self,*args:None
run_quote_request=ns['ApiWorker'].run
ns['ApiWorker'].run=lambda self:self.failed.emit('offline thickness test')


class ThicknessDropdown(unittest.TestCase):
    def setUp(self):
        self.window=Window()
        self.window._scheme2_loading_order=True
        self.combo=self.window.cabinet_body_thickness_spin
        self.addCleanup(self.window.close)

    def test_free_numeric_input_default_precision_and_range(self):
        self.assertIsInstance(self.combo,QDoubleSpinBox)
        self.assertEqual(self.combo.value(),1.5)
        self.assertEqual(self.combo.decimals(),3)
        self.assertEqual(self.combo.suffix(),' mm')
        self.assertEqual(self.window.thickness_surcharge_coefficient_spin.value(),10)

    def test_selection_emits_numeric_value_and_invalidates_old_calculation(self):
        self.assertIsInstance(self.combo,QDoubleSpinBox)
        spy=QSignalSpy(self.combo.valueChanged)
        self.window.current_result={'formula':{},'quick':{}}
        self.combo.setValue(2.35)
        self.assertEqual(self.combo.value(),2.35)
        self.assertIsNone(self.window.current_result)
        self.assertEqual(spy.count(),1)
        self.assertEqual(spy.at(0),[2.35])
        self.assertIn('重新计算',self.window.risk_label.text())

    def test_order_page_state_restores_numeric_thickness_without_signals(self):
        self.combo.setValue(2.5)
        snapshot=ui._capture_scheme2_page_state(self.window)
        self.assertEqual(snapshot['spins']['cabinet_body_thickness_spin'],2.5)
        self.combo.setValue(1.5)
        spy=QSignalSpy(self.combo.valueChanged)
        ui._restore_scheme2_page_state(self.window,snapshot)
        self.assertEqual(self.combo.value(),2.5)
        self.assertEqual(spy.count(),0)

    def test_reset_restores_default_and_keeps_waste_factor_independent(self):
        self.combo.setValue(2.0)
        self.window.waste_factor_spin.setValue(1.4)
        self.assertEqual(self.combo.value(),2.0)
        self.window.reset_current_cabinet()
        self.assertEqual(self.combo.value(),1.5)
        self.assertEqual(self.window.waste_factor_spin.value(),1.2)

    def test_selected_thickness_is_sent_as_numeric_api_parameter(self):
        self.combo.setValue(2.5)
        worker=SimpleNamespace(
            parent=lambda:self.window, _name_frozen_session=None,
            url='https://offline.invalid/api/quotes/calculate-dual',
            payload={'cabinet_body_thickness_mm':1.5},
            progress=MagicMock(), succeeded=MagicMock(), failed=MagicMock(),
        )
        response=MagicMock()
        response.headers={}
        response.read.return_value=b'{"formula_cost":{},"quick_quote":{}}'
        with patch.object(layout.urllib.request,'urlopen') as request:
            request.return_value.__enter__.return_value=response
            run_quote_request(worker)
        worker.failed.emit.assert_not_called()
        worker.succeeded.emit.assert_called_once()
        payload=json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['cabinet_body_thickness_mm'],2.5)
        self.assertEqual(payload['waste_factor'],1.2)

    def test_legacy_value_is_preserved_without_silent_clamping(self):
        self.combo.setValue(.6)
        self.assertEqual(self.combo.value(),.6)
        self.combo.setValue(2.375)
        self.assertEqual(self.combo.value(),2.375)

    def test_keyboard_input_accepts_nonpreset_thickness_and_resets_default_coefficient(self):
        self.window.show()
        self.combo.setFocus()
        QTest.keyClick(self.combo,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(self.combo,'2.375')
        QTest.keyClick(self.combo,Qt.Key.Key_Return)
        self.assertEqual(self.combo.value(),2.375)
        coefficient=self.window.thickness_surcharge_coefficient_spin
        coefficient.setValue(15)
        self.combo.setValue(3.25)
        self.assertEqual(coefficient.value(),10)
        self.window._scheme2_dirty=False


if __name__=='__main__':
    unittest.main()
