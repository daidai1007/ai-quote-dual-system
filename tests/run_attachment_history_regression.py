"""Run existing quote/print/export fixtures with updates and external IO blocked."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
CASES=('verify_attachment_export_snapshot.py','verify_attachment_summary_print.py','verify_quote_export_customer.py')
if len(sys.argv)>1:
    import runpy
    from unittest.mock import patch
    sys.path[:0]=[str(ROOT/'desktop_client'),str(ROOT/'tests')]
    os.environ['QT_QPA_PLATFORM']='offscreen'
    os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(ROOT/'test-output/attachment-history-private-cache')
    (ROOT/'outputs').mkdir(exist_ok=True)
    import client_update_ui
    filename=sys.argv[1]
    if filename not in CASES:raise ValueError('Unknown local fixture')
    sys.argv=[filename]
    with patch.object(client_update_ui,'UpdateController',lambda *_:None),patch('urllib.request.urlopen',side_effect=RuntimeError('External network blocked in history regression')):
        runpy.run_path(str(ROOT/'tests'/filename),run_name='__main__')
else:
    for filename in CASES:
        result=subprocess.run([sys.executable,__file__,filename],cwd=ROOT,env=os.environ)
        if result.returncode:raise SystemExit(result.returncode)
