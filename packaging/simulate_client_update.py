"""Repeatable LOOPBACK simulation. Never launches or edits the actual client.

Builds a tiny Windows probe EXE, signs an update, serves it on 127.0.0.1,
downloads it and exercises the real updater including real process startup.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from update_test_support import LocalSource
from client_update_core import atomic_json, check_release, download_update, read_json
import client_update_runner as runner


def simulate(folder, fail):
    folder.mkdir(parents=True)
    fixture = LocalSource(folder, real_exe=True, fail=fail)
    children = []
    parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.2)'])
    try:
        envelope = check_release(fixture.config, '2026.10.20.04')
        job_path = download_update(fixture.config, envelope, fixture.install, '2026.10.20.04', copy_runner=False)
        job = read_json(job_path); job['parent_pid'] = parent.pid; atomic_json(job_path, job)
        original = runner.launch_client
        def track(*args, **kwargs):
            process = original(*args, **kwargs); children.append(process); return process
        with patch.object(runner, 'launch_client', side_effect=track):
            result = runner.execute_job(job_path, health_timeout=5, parent_timeout=5)
        expected = 'rolled_back' if fail else 'completed'
        if result['status'] != expected: raise RuntimeError(result)
        for name, content in fixture.preserved.items():
            if name == runner.ENTRY or name.startswith('_internal/'): continue
            if (fixture.install / name).read_bytes() != content: raise RuntimeError('User file changed: ' + name)
        result.update(user_files_identical=True, production_writes=0, mock_executable=True)
        atomic_json(folder / 'simulation-result.json', result)
        return result
    finally:
        for process in [parent, *children]:
            if process.poll() is None: process.terminate()
            process.wait(timeout=10)
        fixture.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['success', 'rollback', 'all'], default='all')
    args = parser.parse_args()
    root = ROOT / 'outputs' / ('local-update-simulation-' + uuid.uuid4().hex[:12])
    with patch.dict(os.environ, LOCALAPPDATA=str(root / 'profile')):
        results = []
        for name, fail in [('success', False), ('rollback', True)]:
            if args.scenario in {name, 'all'}: results.append(simulate(root / name, fail))
    print(json.dumps({'output': str(root), 'results': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
