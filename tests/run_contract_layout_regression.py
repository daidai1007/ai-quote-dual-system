"""Offline reader/state regressions; prevent automatic updates or external IO."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=('verify_contract_ledger_reader.py','verify_contract_ledger_state.py','verify_contract_customer_flow.py',
       'verify_contract_defaults.py','verify_contract_identity.py','verify_contract_template_sharing.py','verify_customer_profiles.py')
if len(sys.argv)>1:
    import runpy
    import tempfile
    from unittest.mock import patch
    sys.path[:0]=[str(ROOT/'desktop_client'),str(ROOT/'tests')]
    name=sys.argv[1]
    if name not in FILES:raise ValueError('Unknown offline test')
    import client_update_ui
    local_temp=ROOT/'test-output/contract-layout/runtime-temp';local_temp.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(local_temp)
    os.environ['AI_QUOTE_ORDER_CACHE_ROOT']=str(ROOT/'test-output/contract-layout/state-cache')
    sys.argv=[name]
    with patch.object(client_update_ui,'UpdateController',lambda *_:None),patch('urllib.request.urlopen',side_effect=AssertionError('External network blocked in layout regression')):
        runpy.run_path(str(ROOT/'tests'/name),run_name='__main__')
else:
    for name in FILES:
        result=subprocess.run([sys.executable,__file__,name],cwd=ROOT)
        if result.returncode:raise SystemExit(result.returncode)
