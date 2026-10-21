"""Signed, opt-in client updates. No quote API credentials or user files involved.

Transport and staging are usable without Qt. The updater executes from an
independent copy of the OLD runtime, never the runtime it is replacing.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

ENTRY = "AIQuoteDualSystem_layout_v0.exe"
MAX_PACKAGE = 1024 * 1024 * 1024
MAX_EXPANDED = 3 * MAX_PACKAGE
MAX_FILES = 30000
TIMEOUT = 8
CONFIG_NAME = "update_config.json"
PUBLIC_CA_BUNDLE = "_internal/certifi/cacert.pem"
ROOT_FILES = {ENTRY.casefold(), "project-license.txt", "third_party_notices.txt", "aiquotedualsystem.ico"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
LAN_NETWORKS = tuple(ipaddress.IPv4Network(network) for network in
                     ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class UpdateError(RuntimeError):
    pass


class Cancelled(UpdateError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){3}", value):
        raise UpdateError("更新版本号格式错误")
    return tuple(map(int, value.split(".")))


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_config(install_root):
    """No baked-in remote URL. Explicit local test override never edits user config."""
    path = Path(os.getenv("AI_QUOTE_UPDATE_CONFIG") or Path(install_root) / CONFIG_NAME)
    if not path.is_file():
        return {"enabled": False}
    value = read_json(path)
    if not isinstance(value, dict) or value.get("enabled") is not True:
        return {"enabled": False}
    # No arbitrary public HTTP and no API token forwarding, including redirects.
    validate_url(value.get("manifest_url", ""), lan_http_origin=value.get("lan_http_origin", ""))
    try:
        if len(base64.b64decode(value["public_key"], validate=True)) != 32:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as error:
        raise UpdateError("更新验证公钥未正确配置") from error
    return value


def _parse_update_url(url):
    # urlsplit strips some control characters. Reject them BEFORE parsing.
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url or "#" in url:
        raise UpdateError("更新地址不受信任")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None
                or not parsed.hostname or "%" in parsed.netloc or parsed.netloc.endswith(":") or port == 0):
            raise ValueError()
    except ValueError as error:
        raise UpdateError("更新地址不受信任") from error
    return parsed, (parsed.scheme, parsed.hostname, port if port is not None else (443 if parsed.scheme == "https" else 80))


def _lan_http_identity(value):
    if value is None or value == "":
        return None
    parsed, identity = _parse_update_url(value)
    try:
        address = ipaddress.IPv4Address(parsed.hostname)
    except ipaddress.AddressValueError as error:
        raise UpdateError("内网 HTTP 更新地址必须使用明确的私有 IPv4 地址，不支持域名或通配符") from error
    # Deliberately RFC1918 only, not is_private (which includes other special IPs).
    if (parsed.scheme != "http" or str(address) != parsed.hostname or not any(address in net for net in LAN_NETWORKS)
            or parsed.path not in {"", "/"} or parsed.query or "?" in value):
        raise UpdateError("内网 HTTP 更新地址只能配置一个私有 IPv4 的源地址，例如 http://192.168.1.100:8897")
    return identity


def validate_url(url, origin=None, *, lan_http_origin=""):
    parsed, identity = _parse_update_url(url)
    pinned = _lan_http_identity(lan_http_origin)
    if pinned is not None and identity != pinned:
        raise UpdateError("更新地址与明确配置的内网 IP 或端口不一致")
    if parsed.scheme == "http" and pinned is None and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise UpdateError("HTTP 更新仅允许本机模拟服务或明确配置的内网 IP 和端口")
    if origin and identity != validate_url(origin, lan_http_origin=lan_http_origin):
        raise UpdateError("更新包地址必须与版本清单同源")
    return identity


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, config=None, initial_url=None):
        super().__init__()
        self.config = config or {}
        self.initial_url = initial_url

    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_url(newurl, self.config.get("manifest_url") or self.initial_url or request.full_url,
                     lan_http_origin=self.config.get("lan_http_origin", ""))
        return super().redirect_request(request, fp, code, message, headers, newurl)


def open_url(url, config=None):
    config = config or {}
    validate_url(url, config.get("manifest_url"), lan_http_origin=config.get("lan_http_origin", ""))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SafeRedirect(config, url))
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "AIQuote-Update/1"}), timeout=TIMEOUT)


def verify_manifest(envelope, config):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        release = envelope["release"]
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(config["public_key"], validate=True))
        key.verify(base64.b64decode(envelope["signature"], validate=True), canonical(release))
    except (KeyError, ValueError, TypeError, InvalidSignature) as error:
        raise UpdateError("更新签名校验失败，未修改当前程序") from error
    if release.get("schema") != 1 or release.get("product") != "AIQuoteDualSystem" or release.get("channel") != config.get("channel", "local"):
        raise UpdateError("更新包不适用于当前程序或更新通道")
    version_tuple(release.get("version"))
    if not isinstance(release.get("size"), int) or not 0 < release["size"] <= MAX_PACKAGE:
        raise UpdateError("更新包大小无效")
    if not re.fullmatch(r"[0-9a-f]{64}", str(release.get("sha256", ""))):
        raise UpdateError("更新包校验信息无效")
    if not isinstance(release.get("notes", ""), str) or len(release.get("notes", "")) > 12000:
        raise UpdateError("更新说明格式错误")
    validate_url(release.get("url", ""), config["manifest_url"], lan_http_origin=config.get("lan_http_origin", ""))
    return release


def check_release(config, current_version):
    if not config.get("enabled"):
        return None
    with open_url(config["manifest_url"], config) as response:
        content = response.read(65537)
    if len(content) > 65536:
        raise UpdateError("更新清单超出大小限制")
    envelope = json.loads(content.decode("utf-8"))
    release = verify_manifest(envelope, config)
    return envelope if version_tuple(release["version"]) > version_tuple(current_version) else None


def safe_member(name):
    """Whitelist program paths; exclude configs, orders, drawings, exports, links."""
    if not isinstance(name, str) or "\\" in name or ":" in name or "\x00" in name:
        raise UpdateError("更新包包含不安全路径")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(p in {"", ".", ".."} or p.rstrip(" .") != p
            or p.split(".")[0].casefold() in RESERVED for p in path.parts):
        raise UpdateError("更新包包含不安全路径")
    if len(path.parts) == 1 and name.casefold() in ROOT_FILES:
        return name
    if len(path.parts) > 1 and path.parts[0] in {"_internal", "runtime"}:
        # Even inside the runtime, never distribute application secrets/settings.
        if (path.name.casefold() in {"client_config.json", CONFIG_NAME, "workspace.json"}
                or path.suffix.casefold() in {".aiquote", ".key"}
                or (path.suffix.casefold() == ".pem" and name != PUBLIC_CA_BUNDLE)):
            raise UpdateError("更新包不得包含用户配置、订单或密钥")
        return name
    raise UpdateError("更新包试图覆盖用户配置或本地文件")


def validate_public_ca_bundle(value):
    """Only the known certifi public certificate bundle, never private PEM keys."""
    from cryptography import x509
    labels = re.findall(rb"-----BEGIN ([^\r\n-]+)-----", value)
    if (len(value) > 1024 * 1024 or not labels or any(label != b"CERTIFICATE" for label in labels)
            or b"PRIVATE KEY" in value.upper()):
        raise UpdateError("更新包中的 CA 证书文件无效或包含私钥")
    try:
        certificates = x509.load_pem_x509_certificates(value)
        if len(certificates) != len(labels):
            raise ValueError("Certificate count mismatch")
    except ValueError as error:
        raise UpdateError("更新包中的 CA 证书文件无效") from error


def reject_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise UpdateError("更新路径不得经过链接或联接目录")


def unpack(package, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    members, seen, total = [], set(), 0
    with zipfile.ZipFile(package) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise UpdateError("更新包文件数超出限制")
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = safe_member(item.filename)
            if name.casefold() in seen or stat.S_ISLNK(item.external_attr >> 16):
                raise UpdateError("更新包包含重复路径或链接")
            seen.add(name.casefold())
            total += item.file_size
            if total > MAX_EXPANDED:
                raise UpdateError("更新包展开大小超出限制")
            members.append((item, name))
        if ENTRY.casefold() not in seen:
            raise UpdateError("更新包缺少主程序")
        if shutil.disk_usage(destination).free < total * 2 + 16 * 1024 * 1024:
            raise UpdateError("磁盘空间不足，未修改当前程序")
        for item, name in members:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("xb") as stream:
                if name == PUBLIC_CA_BUNDLE:
                    value = source.read(1024 * 1024 + 1)
                    validate_public_ca_bundle(value)
                    stream.write(value)
                else:
                    shutil.copyfileobj(source, stream)
    return [name for _item, name in members]


def cache_root(install_root):
    root = Path(os.getenv("LOCALAPPDATA") or tempfile.gettempdir()) / "AIQuoteDualSystem" / "updates"
    identity = hashlib.sha256(str(Path(install_root).resolve()).casefold().encode()).hexdigest()[:20]
    return root / identity


def download_update(config, envelope, install_root, current_version, progress=lambda *_: None, cancelled=lambda: False, copy_runner=True):
    release = verify_manifest(envelope, config)
    if version_tuple(release["version"]) <= version_tuple(current_version):
        raise UpdateError("不允许降级或重复安装")
    install_root = Path(install_root).resolve()
    reject_links(install_root)
    transaction = cache_root(install_root) / uuid.uuid4().hex
    transaction.mkdir(parents=True, exist_ok=False)
    package = transaction / "package.zip"
    h, received = hashlib.sha256(), 0
    try:
        with open_url(release["url"], config) as response, package.open("xb") as stream:
            while True:
                if cancelled():
                    raise Cancelled("下载已取消，当前程序未修改")
                block = response.read(256 * 1024)
                if not block:
                    break
                received += len(block)
                if received > release["size"]:
                    raise UpdateError("更新包大小与清单不一致")
                h.update(block)
                stream.write(block)
                progress(received, release["size"])
        if received != release["size"] or h.hexdigest() != release["sha256"]:
            raise UpdateError("更新包完整性校验失败，未修改当前程序")
        files = unpack(package, transaction / "payload")
        if cancelled():
            raise Cancelled("下载已取消，当前程序未修改")
        if copy_runner:
            progress(release["size"], release["size"])
            runner = transaction / "runner"
            runner.mkdir()
            shutil.copy2(install_root / ENTRY, runner / ENTRY)
            shutil.copytree(install_root / "_internal", runner / "_internal")
        job = {"schema": 1, "install_root": str(install_root), "current_version": current_version,
               "old_exe_sha256": digest(install_root / ENTRY), "config": config, "envelope": envelope,
               "files": files, "parent_pid": os.getpid(), "token": uuid.uuid4().hex,
               "status": "prepared", "workspace": ""}
        atomic_json(transaction / "job.json", job)
        return transaction / "job.json"
    except BaseException:
        # Only our newly created, UUID-scoped cache, never install/user files.
        shutil.rmtree(transaction, ignore_errors=True)
        raise


@contextmanager
def update_lock(root):
    folder = cache_root(root)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "update.lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            if not lock.read(1):
                lock.write(b"0"); lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise UpdateError("另一个更新任务正在进行") from error
            try:
                yield
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_copy(source, target):
    target = Path(target)
    reject_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=target.name + ".client-update-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as dst, open(source, "rb") as src:
            shutil.copyfileobj(src, dst)
            dst.flush(); os.fsync(dst.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.is_file():
            temporary.unlink()


def restore_backup(job_path, job):
    """Idempotent rollback; a crash after restore can safely retry it."""
    tx, install = Path(job_path).parent, Path(job["install_root"])
    for record in reversed(job["backup_files"]):
        name = safe_member(record["path"])
        target = install / name
        reject_links(target)
        if record["existed"]:
            backup = tx / "backup" / name
            if digest(backup) != record["sha256"]:
                raise UpdateError("旧版本备份校验失败，需保留现场人工恢复")
            if not target.is_file() or digest(target) != record["sha256"]:
                atomic_copy(backup, target)
        elif target.is_file():
            target.unlink()
    job["status"] = "rolled_back"
    atomic_json(job_path, job)


def apply_update(job_path, health_check, progress=lambda *_: None):
    """Caller has waited for parent exit. All mutations are journaled and bounded."""
    job_path = Path(job_path).resolve()
    job = read_json(job_path)
    install = Path(job["install_root"])
    tx = job_path.parent
    reject_links(install); reject_links(tx)
    if tx.parent != cache_root(install).resolve() or not re.fullmatch(r"[a-f0-9]{32}", tx.name):
        raise UpdateError("更新事务路径无效")
    if not (install / ENTRY).is_file():
        raise UpdateError("安装目录无效")
    with update_lock(install):
        if job["status"] in {"applying", "checking", "rollback_failed"}:
            restore_backup(job_path, job)
            return {"status": "rolled_back", "version": job["current_version"], "message": "检测到中断的更新，已恢复旧版本"}
        if job["status"] != "prepared":
            raise UpdateError("更新事务已完成或无效")
        release = verify_manifest(job["envelope"], job["config"])
        if version_tuple(release["version"]) <= version_tuple(job["current_version"]):
            raise UpdateError("不允许降级")
        if digest(install / ENTRY) != job["old_exe_sha256"]:
            raise UpdateError("当前程序已发生变化，请重新检查更新")
        if digest(tx / "package.zip") != release["sha256"]:
            raise UpdateError("缓存更新包校验失败")
        # Re-extract the signed archive; never trust a previously extracted tree.
        verified = tx / ("verified-" + uuid.uuid4().hex)
        files = unpack(tx / "package.zip", verified)
        records = []
        for name in files:
            target = install / name
            reject_links(target)
            exists = target.exists()
            if exists and not target.is_file():
                raise UpdateError("更新目标不是普通文件")
            record = {"path": name, "existed": exists, "sha256": digest(target) if exists else ""}
            if exists:
                backup = tx / "backup" / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                if digest(backup) != record["sha256"]:
                    raise UpdateError("旧版本备份校验失败")
            records.append(record)
        job["backup_files"] = records
        job["status"] = "applying"
        atomic_json(job_path, job)
        try:
            for index, name in enumerate(files):
                atomic_copy(verified / name, install / name)
                if digest(install / name) != digest(verified / name):
                    raise UpdateError("程序文件替换校验失败")
                progress(index + 1, len(files))
            job["status"] = "checking"
            atomic_json(job_path, job)
            if not health_check(job):
                raise UpdateError("新版本未通过启动检查")
            job["status"] = "completed"
            atomic_json(job_path, job)
            return {"status": "completed", "version": release["version"], "message": "更新成功，用户配置和本地文件已保留"}
        except Exception as error:
            try:
                restore_backup(job_path, job)
            except Exception as rollback_error:
                job["status"] = "rollback_failed"
                atomic_json(job_path, job)
                raise UpdateError("恢复旧版本未完成，请勿删除更新备份") from rollback_error
            return {"status": "rolled_back", "version": job["current_version"], "message": f"更新失败，已恢复旧版本：{error}"}
