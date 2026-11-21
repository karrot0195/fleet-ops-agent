from __future__ import annotations

import hashlib
import shlex
import time
from pathlib import Path
from typing import Any

from .state import utcnow


class BackupError(Exception):
    exit_code = 4


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path: str | Path) -> tuple[int, str]:
    target = Path(path)
    if not target.is_file():
        raise BackupError(f"backup missing: {target}")
    size = target.stat().st_size
    if size <= 0:
        raise BackupError(f"backup is empty: {target}")
    return size, sha256_file(target)


def remote_checksum(client: Any, ip: str, remote: str) -> str:
    result = client.run(ip, f"sha256sum {shlex.quote(remote)}", need_privilege=True)
    if not result.ok:
        raise BackupError(f"backup checksum failed on {ip}: {(result.stderr or result.stdout).strip()}")
    fields = (result.stdout or "").split()
    if not fields:
        raise BackupError(f"backup checksum unreadable on {ip}: {remote}")
    return fields[0].lower()


def create_backup(client: Any, cfg: Any, ip: str) -> dict[str, Any]:
    timestamp = int(time.time())
    name = str(cfg.tool["name"])
    remote = f"/var/backups/{name}-{timestamp}.tar.gz"
    paths = " ".join(str(path) for path in cfg.tool["config_paths"])
    result = client.run(ip, f"tar czf {remote} {paths}", need_privilege=True, check=False)
    if not result.ok:
        raise BackupError(f"backup failed on {ip}: {(result.stderr or result.stdout).strip()}")
    expected = remote_checksum(client, ip, remote)
    local = cfg.resolve("paths.backups_dir") / ip / f"{name}-{timestamp}.tar.gz"
    downloaded = client.download(ip, remote, local)
    if not downloaded.ok:
        raise BackupError(f"backup download failed for {ip}: {(downloaded.stderr or '').strip()}")
    size, digest = verify_archive(local)
    if digest.lower() != expected:
        raise BackupError(
            f"backup checksum mismatch for {ip}: remote {expected} != local {digest}"
        )
    return {
        "remote_path": remote,
        "local_path": str(local),
        "size_bytes": size,
        "sha256": digest,
        "verified": True,
        "created_at": utcnow(),
    }
