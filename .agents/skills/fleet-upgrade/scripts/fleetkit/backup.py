"""Backup utilities for remote configuration files.

Supports:
- Creating tar archives of remote config paths, downloading them locally.
- Verifying local backups against expected SHA-256 checksums.
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .ssh import SSHClient


class BackupError(Exception):
    exit_code = 3


def _compute_sha256(filepath: str | Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(
    ssh: SSHClient,
    config_paths: list[str],
    tool_name: str,
    ip: str,
    backups_dir: str | Path,
) -> dict[str, Any]:
    """Create a tar archive of remote config paths, download it locally.

    Returns dict with keys: path, checksum, remote_size.
    Raises BackupError on failure.
    """
    config_arg = " ".join(shlex.quote(p) for p in config_paths)
    timestamp = Path(ip).name.replace(".", "_") if "." in ip else ip
    # Use ISO-like timestamp without colons
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"{tool_name}-{ip}-{now}.tar.gz"
    remote_tmp = f"/tmp/.fleet-backup-{timestamp}-{now}.tar.gz"
    local_dir = Path(backups_dir) / ip
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / archive_name

    # Build remote tar command
    escape_cmd = " && ".join(f"touch {shlex.quote(p)} || true" for p in config_paths)
    tar_cmd = f"( {escape_cmd} ) && tar -czf {remote_tmp} {' '.join(shlex.quote(p) for p in config_paths)}"

    result = ssh.run(ip, tar_cmd, check=False)
    if not result.ok:
        raise BackupError(f"failed to create remote backup on {ip}: {result.stderr.strip()}")

    # Download the archive
    dl_result = ssh.download(ip, remote_tmp, str(local_path))
    if not dl_result.ok:
        raise BackupError(f"failed to download backup from {ip}: {dl_result.stderr.strip()}")

    # Clean up remote temp file
    ssh.run(ip, f"rm -f {remote_tmp}", check=False)

    checksum = _compute_sha256(local_path)
    size = local_path.stat().st_size

    return {
        "path": str(local_path),
        "checksum": checksum,
        "remote_size": size,
    }


def verify_backup(backup_path: str | Path, expected_checksum: str) -> bool:
    """Verify a local backup archive matches the expected SHA-256 checksum."""
    actual = _compute_sha256(Path(backup_path))
    return actual == expected_checksum
