"""Scoped regressions in separate, offline Qt processes with temporary settings.

Usage: python tests/run_quote_management_checks.py [verify_*.py ...]
Never launches the installed EXE or reads production business settings.
"""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    'verify_quote_management.py', 'verify_quote_unit_rounding.py',
    'verify_scheme2_formal_quote.py', 'verify_quote_document_progress.py',
    'verify_quote_document_feedback.py', 'verify_quote_scheme_export_registration.py',
    'verify_quote_scheme_restore.py', 'verify_quote_scheme_center.py',
    'verify_quote_scheme_reference_ui.py', 'verify_scheme2_quote_workflow.py',
    'verify_single_action_dock.py', 'verify_new_scheme_workspace_reset.py',
    'verify_quote_analysis.py', 'verify_quote_analysis_full_workflow.py',
    'verify_customer_terminology.py', 'verify_attachment_export_snapshot.py',
    'verify_client_updates.py', 'verify_lan_client_updates.py', 'verify_client_update_ui.py',
)

if len(sys.argv)>1 and sys.argv[1]=='--child':
    with tempfile.TemporaryDirectory(prefix='qm-offline-') as temporary:
        os.environ['QT_QPA_PLATFORM']='offscreen'
        os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=temporary
        os.environ['AI_QUOTE_UPDATE_CONFIG']=str(Path(temporary)/'updates.json')
        Path(os.environ['AI_QUOTE_UPDATE_CONFIG']).write_text('{}',encoding='utf-8')
        from PySide6.QtCore import QSettings
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,temporary)
        suite=sys.argv[2]; sys.argv=[suite]
        # Suites replace this guard with explicit mocks or loopback fixtures.
        with patch('urllib.request.urlopen',side_effect=AssertionError('External network forbidden in offline regressions')):
            runpy.run_path(str(ROOT/'tests'/suite),run_name='__main__')
else:
    failures=[]
    for suite in sys.argv[1:] or SUITES:
        try:
            result=subprocess.run([sys.executable,__file__,'--child',suite],cwd=ROOT,
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,
                env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            print(f'{suite}: {"PASS" if result.returncode==0 else "FAIL"}',flush=True)
            if result.returncode:
                failures.append(suite); print(result.stdout[-5000:]+result.stderr[-5000:],flush=True)
        except subprocess.TimeoutExpired:
            failures.append(suite); print(f'{suite}: TIMEOUT',flush=True)
    print(f'{len(failures)} failed',flush=True)
    sys.exit(bool(failures))
