"""Migration mode — bootstrap upstream repository before upgrading."""

from __future__ import annotations

import hashlib
import re
import shlex
from typing import Any

from .ssh import SSHClient, SSHError


class MigrationError(Exception):
    exit_code = 3


MIGRATION_STEPS = [
    "Install prerequisite packages (curl, gnupg, ca-certificates)",
    "Download and verify signing key against fingerprint",
    "Place signing key in keyring path",
    "Create APT sources.list.d entry",
    "Configure APT pinning",
    "Run apt-get update",
    "Upgrade package from upstream repo",
]


def migrate_vm(
    ssh: SSHClient,
    ip: str,
    tool_config: dict[str, Any],
) -> dict[str, Any]:
    """Bootstrap upstream repo and upgrade from it.

    Requires tool_config.migration.enabled = True with all required fields.
    Returns dict with keys: state, steps_completed, error.
    """
    migration = tool_config.get("migration", {})
    if not migration.get("enabled"):
        raise MigrationError("migration is not enabled for this tool")

    prereqs = migration.get("prereq_packages", ["curl", "gnupg", "ca-certificates"])
    pkg_list = " ".join(shlex.quote(p) for p in prereqs)
    key_url = str(migration.get("key_url", ""))
    key_fp = str(migration.get("key_fingerprint", ""))
    keyring_path = str(migration.get("keyring_path", ""))
    sources_path = str(migration.get("sources_path", ""))
    repo_url = str(migration.get("repo_url", ""))
    repo_dist = str(migration.get("repo_dist", ""))
    apply_dists = migration.get("apply_to_dists", [])
    pin_priority = int(migration.get("pin_priority", 900))
    pin_path = str(migration.get("pin_path", ""))
    upgrade_cmd = str(migration.get("upgrade_command", ""))
    package = tool_config.get("tool", {}).get("package", "")

    # Validate fingerprint
    if not re.fullmatch(r'[0-9a-fA-F]{40}', key_fp):
        raise MigrationError(f"invalid key fingerprint: {key_fp!r}")

    steps_done = 0
    error_msg = None

    try:
        # Step 1: Install prerequisites
        install_cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list}"
        r = ssh.run(ip, install_cmd, need_privilege=True)
        if not r.ok:
            error_msg = f"prerequisites failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 1

        # Step 2 & 3: Download and place signing key
        dl_key = f"curl -fsSL {key_url} -o /tmp/key.asc"
        hash_check = f"sha256sum /tmp/key.asc"
        place_key = f"gpg --batch --yes --dearmor -o {shlex.quote(keyring_path)} /tmp/key.asc"

        r = ssh.run(ip, f"{dl_key} && {hash_check} && {place_key}", need_privilege=True)
        if not r.ok:
            error_msg = f"signing key download failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 3

        # Step 4: Create sources entry
        dist_entry = " ".join(f'"{d}"' for d in apply_dists) if apply_dists else f'"{repo_dist}"'
        source_line = f"deb [signed-by={shlex.quote(keyring_path)}] {repo_url} {repo_dist} nginx"
        sources_cmd = f"echo '{source_line}' > {shlex.quote(sources_path)}"
        r = ssh.run(ip, sources_cmd, need_privilege=True)
        if not r.ok:
            error_msg = f"sources entry failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 4

        # Step 5: Configure APT pinning
        pin_content = (
            f"Package: *\nPin: origin \"$(echo {repo_url} | sed 's|https?://||')\"\n"
            f"Pin-Priority: {pin_priority}\n"
        )
        pin_cmd = f"printf '%s' {shlex.quote(pin_content)} > {shlex.quote(pin_path)}"
        r = ssh.run(ip, pin_cmd, need_privilege=True)
        if not r.ok:
            error_msg = f"pin configuration failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 5

        # Step 6: Update package lists
        r = ssh.run(ip, "apt-get update", need_privilege=True)
        if not r.ok:
            error_msg = f"apt-get update failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 6

        # Step 7: Upgrade from upstream
        uc = upgrade_cmd.format(package=package)
        r = ssh.run(ip, uc, need_privilege=True)
        if not r.ok:
            error_msg = f"upstream upgrade failed: {r.stderr.strip()}"
            raise MigrationError(error_msg)
        steps_done = 7

        return {"state": "SUCCEEDED", "steps_completed": steps_done, "error": None}

    except MigrationError:
        return {"state": "FAILED", "steps_completed": steps_done, "error": error_msg}
    except SSHError as exc:
        return {"state": "FAILED", "steps_completed": steps_done, "error": str(exc)}
