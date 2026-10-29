"""Prepare PUBLIC bridge configuration only; never build/sign/upload a client."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_client"))
from client_update_core import atomic_json, digest, read_json, reject_links, verify_manifest
from client_update_bridge import configuration


def prepare(final_manifest, final_package, update_config, bridge_version, output):
    config = read_json(update_config)
    envelope = read_json(final_manifest)
    release = verify_manifest(envelope, config)
    package = Path(final_package)
    reject_links(package)
    if package.stat().st_size != release["size"] or digest(package) != release["sha256"]:
        raise ValueError("最终程序包与签名清单不一致")
    spec = configuration(bridge_version, envelope, config)
    output = Path(output)
    reject_links(output)
    if output.exists():
        raise ValueError("过渡配置已存在，不覆盖现有交付")
    atomic_json(output, spec)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("final-manifest", "final-package", "update-config", "bridge-version", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    spec = prepare(args.final_manifest, args.final_package, args.update_config, args.bridge_version, args.output)
    print("PUBLIC_BRIDGE_CONFIGURATION=PASS; bridge=" + spec["bridge_version"]
          + "; final=" + spec["final_envelope"]["release"]["version"] + "; client_built=False; server_written=False")


if __name__ == "__main__":
    main()
