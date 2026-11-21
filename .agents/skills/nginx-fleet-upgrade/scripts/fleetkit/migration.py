from __future__ import annotations

import shlex
from typing import Any

from .verdict import matching_holds, parse_apt_policy


class MigrationError(Exception):
    exit_code = 4


def migration_settings(cfg: Any) -> dict[str, Any]:
    prereqs = [str(item) for item in (cfg.get("migration.prereq_packages") or [])]
    return {
        "enabled": bool(cfg.get("migration.enabled")),
        "repo_url": str(cfg.get("migration.repo_url") or ""),
        "repo_dist": str(cfg.get("migration.repo_dist") or ""),
        "apply_to_dists": [str(item) for item in (cfg.get("migration.apply_to_dists") or [])],
        "key_url": str(cfg.get("migration.key_url") or ""),
        "key_fingerprint": str(cfg.get("migration.key_fingerprint") or ""),
        "keyring_path": str(cfg.get("migration.keyring_path") or ""),
        "sources_path": str(cfg.get("migration.sources_path") or ""),
        "pin_path": str(cfg.get("migration.pin_path") or ""),
        "pin_priority": int(cfg.get("migration.pin_priority", 900)),
        "stub_default_conf": bool(cfg.get("migration.stub_default_conf", True)),
        "prereq_packages": " ".join(shlex.quote(item) for item in prereqs),
    }


def bootstrap_script(cfg: Any) -> str:
    settings = migration_settings(cfg)
    sources_line = (
        f"deb [signed-by={settings['keyring_path']}] {settings['repo_url']} "
        f"{settings['repo_dist']} nginx"
    )
    pin_line = (
        "Package: *\nPin: origin nginx.org\nPin: release o=nginx\n"
        f"Pin-Priority: {settings['pin_priority']}"
    )
    lines = [
        "set -e",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
        + settings["prereq_packages"],
        f"curl -fsSL {shlex.quote(settings['key_url'])} | gpg --dearmor --yes -o "
        + shlex.quote(settings["keyring_path"]),
        "GNUPGHOME=\"$(mktemp -d)\" gpg --batch --quiet --no-tty "
        "--import-options import-show --import " + shlex.quote(settings["keyring_path"])
        + " | grep -qi " + shlex.quote(settings["key_fingerprint"])
        + " || { echo 'nginx signing key fingerprint mismatch' >&2; exit 50; }",
        f"printf {shlex.quote(sources_line + chr(10))} > " + shlex.quote(settings["sources_path"]),
        f"printf {shlex.quote(pin_line)} > " + shlex.quote(settings["pin_path"]),
    ]
    if settings["stub_default_conf"]:
        lines.append("mkdir -p /etc/nginx/conf.d")
        lines.append(
            "test -f /etc/nginx/conf.d/default.conf || "
            "printf '# stub: managed by nginx-fleet-upgrade\\n' > /etc/nginx/conf.d/default.conf"
        )
    lines.append("apt-get update -q")
    return "\n".join(lines) + "\n"


def policy_command() -> str:
    return "apt-cache policy nginx"


def candidate_origin(policy_output: str) -> str | None:
    """Return the repository URL of the candidate version from apt-cache policy output."""
    return parse_apt_policy(policy_output)["origin"]


def repo_active(policy_output: str) -> bool:
    origin = candidate_origin(policy_output)
    return bool(origin) and "nginx.org" in origin.lower()


def migration_eligible(record: dict[str, Any], cfg: Any) -> str | None:
    """Return None when the record may migrate to the upstream repo, else the refusal reason.

    A distro-verdict of BLOCKED does not by itself refuse migration: the most common
    cause (unexpected distro mirror origin) is irrelevant because migration replaces
    the package source. Health is judged from the evidence directly.
    """
    settings = migration_settings(cfg)
    if not settings["enabled"]:
        return "migration disabled in config"
    verdict = record.get("verdict")
    if verdict in {"UNREACHABLE", "SKIP"}:
        return f"verdict {verdict}; migration requires a reachable VM with nginx installed"
    evidence = record.get("evidence") or {}
    codename = evidence.get("codename")
    if codename not in settings["apply_to_dists"]:
        return f"distro {codename or 'unknown'} not in migration.apply_to_dists"
    if not evidence.get("binary_present"):
        return "nginx binary not present"
    if not evidence.get("config_test_ok", True):
        return "configuration test failed"
    held = matching_holds(evidence.get("held_packages") or [], cfg.tool["hold_patterns"])
    if held:
        return "package held: " + ", ".join(held)
    if evidence.get("third_party_modules"):
        return "third-party module requires review: " + ", ".join(evidence["third_party_modules"])
    return None
