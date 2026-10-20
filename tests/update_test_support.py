from __future__ import annotations
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop_client"))
sys.path.insert(0, str(ROOT / "packaging"))
from client_update_core import ENTRY, atomic_json, canonical, digest
from make_client_update import build, generate_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass


class LocalSource:
    def __init__(self, root, real_exe=False, fail=False):
        self.root = Path(root)
        self.install = self.root / "模拟客户端"
        self.source = self.root / "new-client"
        self.web = self.root / "http"
        self.web.mkdir(); self.install.mkdir(); self.source.mkdir()
        for folder in (self.install, self.source): (folder / "_internal").mkdir()
        if real_exe:
            compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
            subprocess.run([str(compiler), "/nologo", "/target:winexe", "/out:" + str(self.install / ENTRY),
                            str(ROOT / "tests/update_probe.cs")], check=True, capture_output=True)
        else: (self.install / ENTRY).write_bytes(b"old-exe")
        shutil.copy2(self.install / ENTRY, self.source / ENTRY)
        (self.install / "_internal/version.txt").write_text("2026.10.20.04\nhealthy")
        (self.source / "_internal/version.txt").write_text("2026.10.20.05\n" + ("fail" if fail else "healthy"))
        (self.source / "_internal/new-library.dll").write_bytes(b"new-library")
        for name, data in {"client_config.json": b'{"private":"keep-this"}', "update_config.json": b'{"enabled":false}',
                           "output/报价单.xlsx": b"existing-quote", "drawings/图纸.pdf": b"drawing",
                           "orders/订单.aiquote": b"existing-order", "custom-note.txt": b"local-note"}.items():
            path = self.install / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.preserved = {p.relative_to(self.install).as_posix(): p.read_bytes() for p in self.install.rglob("*") if p.is_file()}
        self.key = self.root / "private" / "signing.key"
        self.public = generate_key(self.key)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(self.web)))
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.config = {"enabled": True, "manifest_url": self.url + "/manifest.json", "public_key": self.public, "channel": "local"}
        self.envelope = build(self.source, self.web, self.key, "2026.10.20.05", self.url, "本地模拟更新\n保留用户文件")

    def resign(self, release):
        key = Ed25519PrivateKey.from_private_bytes(self.key.read_bytes())
        envelope = {"release": release, "signature": base64.b64encode(key.sign(canonical(release))).decode()}
        atomic_json(self.web / "manifest.json", envelope)
        self.envelope = envelope
        return envelope

    def repack(self, names):
        package = self.web / Path(self.envelope["release"]["url"]).name
        with zipfile.ZipFile(package, "w") as archive:
            for name, value in names: archive.writestr(name, value)
        release = dict(self.envelope["release"], sha256=digest(package), size=package.stat().st_size)
        return self.resign(release)

    def assert_user_files(self, case):
        for name, content in self.preserved.items():
            if name == ENTRY or name.startswith("_internal/"): continue
            case.assertEqual((self.install / name).read_bytes(), content, name)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
