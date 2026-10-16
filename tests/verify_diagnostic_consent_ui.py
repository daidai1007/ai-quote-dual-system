import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget  # noqa: E402
import scheme2_ui  # noqa: E402


app = QApplication.instance() or QApplication([])
window = QWidget()
window.quote_export_items_snapshot = lambda: [{
    "product_code": "JM", "model_code": "JM-1200", "specification": "1200*400*1400",
    "quantity": 1, "formula": {"material_cost": 473.98},
}]
window.scheme2_diagnostic_button = QPushButton("提交诊断报告")
window._scheme2_diagnostic_worker = None
window._scheme2_diagnostic_api_url = "https://quote.example/api/quotes/calculate-dual"
window._scheme2_diagnostic_headers_factory = lambda: {"X-AI-Quote-Key": "secret"}

with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected), \
        patch.object(scheme2_ui, "_DiagnosticSubmissionWorker") as worker:
    scheme2_ui._submit_diagnostic_report(window)
    worker.assert_not_called()
    assert window.scheme2_diagnostic_button.isEnabled()

with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
        patch.object(scheme2_ui, "_DiagnosticSubmissionWorker") as worker:
    scheme2_ui._submit_diagnostic_report(window)
    worker.assert_called_once()
    worker.return_value.start.assert_called_once()
    report = worker.call_args.args[2]
    assert report["quote_items"][0]["model_code"] == "JM-1200"
    assert report["quote_items"][0]["formula"]["material_cost"] == 473.98

print("diagnostic consent UI test passed")
