"""Run the FROZEN updater against disposable native mock clients, loopback only."""
from __future__ import annotations
import ctypes
import argparse
from contextlib import nullcontext
from ctypes import wintypes
import http.client
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import time
from unittest.mock import patch

from update_test_support import LocalSource
from client_update_core import ENTRY, atomic_json, cache_root, download_update, read_json


def owned_children(parent):
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    result = []
    try:
        entry = ProcessEntry(); entry.dwSize = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == parent and entry.szExeFile == ENTRY:
                result.append(int(entry.th32ProcessID))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def stop_owned(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100001, False, pid)
    if handle:
        try:
            kernel.TerminateProcess(handle, 0); kernel.WaitForSingleObject(handle, 10000)
        finally: kernel.CloseHandle(handle)


def main(bundle, lan_http=False):
    entry = Path(bundle).resolve() / ENTRY
    if not entry.is_file(): raise ValueError('Missing bundle EXE')
    for fail in (False, True):
        with tempfile.TemporaryDirectory(prefix='quote-frozen-update-') as temp, patch.dict(os.environ, LOCALAPPDATA=temp, QT_QPA_PLATFORM='offscreen'):
            fixture = LocalSource(Path(temp), real_exe=True, fail=fail)
            if lan_http:
                origin = f'http://192.168.50.20:{fixture.server.server_port}'
                fixture.config.update(manifest_url=origin + '/manifest.json', lan_http_origin=origin)
                fixture.envelope = fixture.resign(dict(fixture.envelope['release'],
                    url=fixture.envelope['release']['url'].replace(fixture.url, origin)))
            def connect_local(connection):
                if (connection.host, connection.port) != ('192.168.50.20', fixture.server.server_port):
                    raise AssertionError('Unexpected connection destination')
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(connection.timeout)
                sock.connect(('127.0.0.1', fixture.server.server_port))
                connection.sock = sock
            parent = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(.2)'])
            helper = None
            try:
                with patch.object(http.client.HTTPConnection, 'connect', connect_local) if lan_http else nullcontext():
                    job_path = download_update(fixture.config, fixture.envelope, fixture.install, '2026.10.20.04', copy_runner=False)
                job = read_json(job_path); job['parent_pid'] = parent.pid; atomic_json(job_path, job)
                helper = subprocess.Popen([str(entry), '--client-updater', str(job_path)], cwd=entry.parent,
                                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                result_path = cache_root(fixture.install) / 'last-result.json'
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and not result_path.is_file():
                    if helper.poll() is not None: raise RuntimeError('Frozen updater exited: ' + str(helper.returncode))
                    time.sleep(.1)
                if not result_path.is_file(): raise TimeoutError('No result from frozen updater')
                result = read_json(result_path)
                if result['status'] != ('rolled_back' if fail else 'completed'): raise AssertionError(result)
                for name, data in fixture.preserved.items():
                    if name == ENTRY or name.startswith('_internal/'): continue
                    if (fixture.install / name).read_bytes() != data: raise AssertionError('Changed user data: '+name)
                print('FROZEN_UPDATER_' + ('LAN_HTTP_' if lan_http else '') + ('ROLLBACK' if fail else 'SUCCESS') + '=PASS; user_files_identical=True; production_writes=0', flush=True)
            finally:
                if helper:
                    for pid in owned_children(helper.pid): stop_owned(pid)
                    if helper.poll() is None: helper.terminate()
                    helper.wait(timeout=10)
                if parent.poll() is None: parent.terminate()
                parent.wait(timeout=10)
                fixture.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--lan-http', action='store_true')
    args = parser.parse_args()
    main(args.bundle, args.lan_http)
