"""Build a signed PROGRAM-ONLY update. Does not upload or change installed app."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))
from client_update_core import (ENTRY, ROOT_FILES, atomic_json, canonical, digest,
                                reject_links, safe_member, validate_url, version_tuple)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def generate_key(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    with path.open("xb") as stream:
        stream.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                       serialization.NoEncryption()))
    return base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")


def build(source, output, key_path, version, base_url, notes, channel="local", lan_http_origin=""):
    version_tuple(version); validate_url(base_url, lan_http_origin=lan_http_origin)
    source, output, key_path = Path(source).resolve(), Path(output).resolve(), Path(key_path).resolve()
    if output == source or source in output.parents or output in key_path.parents:
        raise ValueError("更新输出必须独立于客户端目录，签名私钥必须放在下载目录之外")
    if not (source / ENTRY).is_file(): raise ValueError("客户端目录缺少主 EXE")
    key = Ed25519PrivateKey.from_private_bytes(key_path.read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"AIQuoteDualSystem-{version}.zip"
    if (output / "manifest.json").exists(): raise ValueError("输出中已有版本清单，请使用新的版本目录")
    files = []
    for name in sorted(ROOT_FILES):
        files.extend(p for p in source.iterdir() if p.is_file() and p.name.casefold() == name)
    for folder in ("_internal", "runtime"):
        root = source / folder
        if root.is_dir(): files.extend(p for p in root.rglob("*") if p.is_file())
    with zipfile.ZipFile(package, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            reject_links(path)
            archive.write(path, safe_member(path.relative_to(source).as_posix()))
    release = {"schema": 1, "product": "AIQuoteDualSystem", "channel": channel,
               "version": version, "url": base_url.rstrip("/") + "/" + package.name,
               "size": package.stat().st_size, "sha256": digest(package), "notes": notes,
               "published_at": datetime.now(timezone.utc).isoformat()}
    envelope = {"release": release, "signature": base64.b64encode(key.sign(canonical(release))).decode("ascii")}
    atomic_json(output / "manifest.json", envelope)
    return envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    key = sub.add_parser("keygen"); key.add_argument("--private-key", required=True)
    release = sub.add_parser("build")
    for name in ("source", "output", "private-key", "version", "base-url", "notes"):
        release.add_argument("--" + name, required=True)
    release.add_argument("--channel", default="local")
    release.add_argument("--lan-http-origin", default="", help="Explicit RFC1918 IPv4 HTTP origin, e.g. http://192.168.1.100:8897")
    args = parser.parse_args()
    if args.command == "keygen":
        print("Public key: " + generate_key(args.private_key))
    else:
        envelope = build(args.source, args.output, args.private_key, args.version, args.base_url,
                         Path(args.notes).read_text(encoding="utf-8-sig"), args.channel, args.lan_http_origin)
        print("Local update prepared: " + envelope["release"]["version"])


if __name__ == "__main__": main()
