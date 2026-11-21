from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    exit_code = 2


class PreflightError(Exception):
    exit_code = 5


DEFAULTS: dict[str, Any] = {
    "apiVersion": "nginx-fleet-upgrade/v1",
    "fleet": {"inventory_file": "ip.txt", "source": "doctl"},
    "paths": {
        "records_dir": "plan",
        "backups_dir": "backups",
        "state_dir": ".fleet",
        "log_file": "LOGS.md",
    },
    "ssh": {
        "env_file": ".personal/ssh.env",
        "connect_timeout": 5,
        "command_timeout": 60,
        "strict_host_key_checking": "accept-new",
        "privilege": "auto",
        "multiplex": True,
    },
    "execution": {
        "concurrency": 4,
        "canary_size": 1,
        "retry_rounds": 1,
        "upgrade_command": (
            "DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade {package} "
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
        ),
    },
    "tool": {
        "name": "nginx",
        "package": "nginx",
        "service": "nginx",
        "config_paths": ["/etc/nginx"],
        "version_query": "dpkg-query -W -f='${Version}' nginx",
        "precheck": "nginx -t",
        "allowed_origin_patterns": [
            "archive.ubuntu.com",
            "security.ubuntu.com",
            "ports.ubuntu.com",
            "deb.debian.org",
            "security.debian.org",
        ],
        "hold_patterns": ["nginx", "nginx-*"],
        "allowed_dynamic_module_dirs": ["/usr/lib/nginx/modules"],
        "verify": {
            "http": {"enabled": True, "url": "http://127.0.0.1/", "timeout": 10},
            "https": {"enabled": "auto", "url": "https://127.0.0.1/", "timeout": 10},
            "require_status": [],
        },
        "drift_patterns": ["*.dpkg-dist", "*.dpkg-new", "*.ucf-dist"],
    },
    "logging": {"redact": []},
    "migration": {
        "enabled": False,
        "repo_url": "https://nginx.org/packages/ubuntu",
        "repo_dist": "noble",
        "apply_to_dists": [],
        "key_url": "https://nginx.org/keys/nginx_signing.key",
        "key_fingerprint": "573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62",
        "keyring_path": "/usr/share/keyrings/nginx-archive-keyring.gpg",
        "sources_path": "/etc/apt/sources.list.d/nginx.list",
        "pin_path": "/etc/apt/preferences.d/99nginx",
        "pin_priority": 900,
        "stub_default_conf": True,
        "prereq_packages": ["curl", "gnupg", "ca-certificates"],
        "upgrade_command": (
            "DEBIAN_FRONTEND=noninteractive apt-get install -y {package} "
            '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
        ),
    },
}


def _allowed_from(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _allowed_from(value) if isinstance(value, dict) else None
        for key, value in defaults.items()
    }


_ALLOWED: dict[str, Any] = _allowed_from(DEFAULTS)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _check_unknown(data: Any, allowed: Any, prefix: str) -> None:
    if allowed is None:
        return
    if not isinstance(data, dict):
        raise ConfigError(f"{prefix or 'config'} must be a mapping")
    for key, value in data.items():
        if key not in allowed:
            where = f"{prefix}.{key}" if prefix else key
            raise ConfigError(f"unknown configuration key: {where}")
        child = allowed[key]
        if child is not None:
            _check_unknown(value, child, f"{prefix}.{key}" if prefix else key)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _int_in(value: Any, low: int, high: int, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    _require(low <= value <= high, f"{label} must be between {low} and {high}")
    return value


def _validate(data: dict[str, Any]) -> None:
    _require(data["apiVersion"] == "nginx-fleet-upgrade/v1", "apiVersion must be nginx-fleet-upgrade/v1")
    _require(data["fleet"]["source"] in {"doctl", "file"}, "fleet.source must be doctl or file")
    _require(bool(str(data["fleet"]["inventory_file"]).strip()), "fleet.inventory_file must not be empty")
    for key in ("records_dir", "backups_dir", "state_dir", "log_file"):
        _require(bool(str(data["paths"][key]).strip()), f"paths.{key} must not be empty")

    ssh = data["ssh"]
    _int_in(ssh["connect_timeout"], 1, 60, "ssh.connect_timeout")
    _int_in(ssh["command_timeout"], 5, 3600, "ssh.command_timeout")
    _require(
        ssh["strict_host_key_checking"] in {"accept-new", "yes"},
        "ssh.strict_host_key_checking must be accept-new or yes",
    )
    _require(ssh["privilege"] in {"auto", "sudo", "root"}, "ssh.privilege must be auto, sudo, or root")
    _require(isinstance(ssh["multiplex"], bool), "ssh.multiplex must be a boolean")
    _require(bool(str(ssh["env_file"]).strip()), "ssh.env_file must not be empty")

    execution = data["execution"]
    _int_in(execution["concurrency"], 1, 16, "execution.concurrency")
    _require(execution["canary_size"] == 1, "execution.canary_size must be 1")
    _int_in(execution["retry_rounds"], 0, 1, "execution.retry_rounds")
    _require("{package}" in str(execution["upgrade_command"]), "execution.upgrade_command must contain {package}")

    tool = data["tool"]
    for key in (
        "name",
        "package",
        "service",
        "version_query",
        "precheck",
    ):
        _require(bool(str(tool[key]).strip()), f"tool.{key} must not be empty")
    _require(
        isinstance(tool["config_paths"], list) and bool(tool["config_paths"]),
        "tool.config_paths must be a non-empty list",
    )
    for key in ("allowed_origin_patterns", "hold_patterns", "allowed_dynamic_module_dirs", "drift_patterns"):
        _require(isinstance(tool[key], list), f"tool.{key} must be a list")
    for proto in ("http", "https"):
        block = tool["verify"][proto]
        _int_in(block["timeout"], 1, 60, f"tool.verify.{proto}.timeout")
        _require(bool(str(block["url"]).strip()), f"tool.verify.{proto}.url must not be empty")
    _require(tool["verify"]["https"]["enabled"] in {"auto", True, False}, "tool.verify.https.enabled must be auto, true, or false")
    _require(isinstance(tool["verify"]["require_status"], list), "tool.verify.require_status must be a list")
    _require(isinstance(data["logging"]["redact"], list), "logging.redact must be a list")

    migration = data["migration"]
    _require(isinstance(migration["enabled"], bool), "migration.enabled must be a boolean")
    if migration["enabled"]:
        for key in ("repo_url", "repo_dist", "key_url", "key_fingerprint", "keyring_path", "sources_path", "pin_path"):
            _require(bool(str(migration[key]).strip()), f"migration.{key} must not be empty when migration is enabled")
        _require(
            isinstance(migration["apply_to_dists"], list) and bool(migration["apply_to_dists"]),
            "migration.apply_to_dists must be a non-empty list when migration is enabled",
        )
        _require(
            len(str(migration["key_fingerprint"])) == 40,
            "migration.key_fingerprint must be a 40-character hex fingerprint",
        )
        _int_in(migration["pin_priority"], 1, 1000, "migration.pin_priority")
        _require(isinstance(migration["prereq_packages"], list), "migration.prereq_packages must be a list")
        _require("{package}" in str(migration["upgrade_command"]), "migration.upgrade_command must contain {package}")


class Config:
    def __init__(self, root: Path, path: Path, data: dict[str, Any]) -> None:
        self.root = root
        self.path = path
        self.data = data

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def resolve(self, dotted: str) -> Path:
        value = Path(str(self.get(dotted))).expanduser()
        return value if value.is_absolute() else (self.root / value)

    @property
    def tool(self) -> dict[str, Any]:
        return self.data["tool"]

    @property
    def ssh(self) -> dict[str, Any]:
        return self.data["ssh"]

    @property
    def execution(self) -> dict[str, Any]:
        return self.data["execution"]


def load_config(root: str | os.PathLike[str], config_path: str | os.PathLike[str] | None = None) -> Config:
    root_path = Path(root).expanduser().resolve()
    path = Path(config_path).expanduser() if config_path else root_path / ".specific" / "nginx-fleet.yaml"
    if not path.is_absolute():
        path = (root_path / path).resolve()
    if not path.is_file():
        raise ConfigError(f"config not found: {path} (run 'fleet.py config --init')")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    _check_unknown(raw, _ALLOWED, "")
    data = _deep_merge(DEFAULTS, raw)
    _validate(data)
    return Config(root_path, path, data)


def load_ssh_env(cfg: Config) -> dict[str, Any]:
    path = cfg.resolve("ssh.env_file")
    if not path.is_file():
        raise PreflightError(f"SSH env file missing: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    missing = [key for key in ("SSH_USER", "SSH_KEY", "SSH_PORT") if not values.get(key)]
    if missing:
        raise PreflightError(f"{path} is missing: {', '.join(missing)}")
    try:
        port = int(values["SSH_PORT"])
    except ValueError as exc:
        raise PreflightError("SSH_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise PreflightError("SSH_PORT must be between 1 and 65535")
    key_path = Path(values["SSH_KEY"]).expanduser()
    if not key_path.is_absolute():
        key_path = (path.parent / key_path).resolve()
    warnings: list[str] = []
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            warnings.append(f"{path} mode is {oct(mode)}; expected 0600")
    except OSError:
        pass
    return {
        "user": values["SSH_USER"],
        "key": str(key_path),
        "port": port,
        "warnings": warnings,
        "env_file": str(path),
    }
