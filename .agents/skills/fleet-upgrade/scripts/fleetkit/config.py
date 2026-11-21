"""Configuration loading, validation, and resolution.

Supports two flavours of configuration:
- Tool configs (.specific/{tool}.yaml) with apiVersion ``fleet-upgrade-tool/v1``.
- Provider configs (.specific/{provider}.yaml) with apiVersion ``fleet-upgrade-provider/v1``.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised when configuration is invalid."""
    exit_code = 2


class PreflightError(Exception):
    """Raised when pre-flight checks fail."""
    exit_code = 5


# ---------------------------------------------------------------------------
# Defaults & helpers
# ---------------------------------------------------------------------------

TOOL_DEFAULTS: dict[str, Any] = {
    "apiVersion": "fleet-upgrade-tool/v1",
    "tool": {
        "name": "",
        "package": "",
        "service": "",
        "config_paths": [],
        "version_query": "",
        "precheck": "",
        "allowed_origin_patterns": [],
        "hold_patterns": [],
        "drift_patterns": [],
        "verify": {
            "http": {"enabled": False, "url": "", "timeout": 10},
            "https": {"enabled": "auto", "url": "", "timeout": 10},
            "require_status": [],
        },
        "upgrade_command": None,
    },
    "migration": {
        "enabled": False,
        "repo_url": "",
        "repo_dist": "",
        "apply_to_dists": [],
        "key_url": "",
        "key_fingerprint": "",
        "keyring_path": "",
        "sources_path": "",
        "pin_path": "",
        "pin_priority": 900,
        "prereq_packages": [],
        "upgrade_command": "",
    },
}

PROVIDER_DEFAULTS: dict[str, Any] = {
    "apiVersion": "fleet-upgrade-provider/v1",
    "provider": {
        "name": "",
        "cli_binary": "",
        "auth_check": "",
        "discover_command": "",
        "output_format": "json",
        "ip_field": None,
        "name_field": "name",
    },
}


def _allowed_from(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _allowed_from(value) if isinstance(value, dict) else None
        for key, value in defaults.items()
    }


_TOOL_ALLOWED: dict[str, Any] = _allowed_from(TOOL_DEFAULTS)
_PROVIDER_ALLOWED: dict[str, Any] = _allowed_from(PROVIDER_DEFAULTS)


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


# ---------------------------------------------------------------------------
# Tool config validation
# ---------------------------------------------------------------------------

def _validate_tool_config(data: dict[str, Any]) -> None:
    _require(data["apiVersion"] == "fleet-upgrade-tool/v1", "apiVersion must be fleet-upgrade-tool/v1")

    tool = data["tool"]
    for key in ("name", "package", "service", "config_paths", "version_query", "precheck"):
        if key == "config_paths":
            _require(isinstance(tool.get(key), list) and len(tool.get(key) or []),
                     f"tool.{key} must be a non-empty list")
        else:
            val = tool.get(key, "")
            _require(bool(str(val).strip()), f"tool.{key} must not be empty")

    for key in ("allowed_origin_patterns", "hold_patterns", "drift_patterns"):
        _require(isinstance(tool[key], list), f"tool.{key} must be a list")

    verify = tool["verify"]
    for proto in ("http", "https"):
        block = verify[proto]
        enabled = block.get("enabled")
        if enabled and enabled is not False and enabled != "auto":
            _require(block.get("url"), f"tool.verify.{proto}.url required when enabled")
            _int_in(block.get("timeout", 10), 1, 60, f"tool.verify.{proto}.timeout")
    _require(verify["https"]["enabled"] in {"auto", True, False},
             "tool.verify.https.enabled must be auto, true, or false")

    migration = data["migration"]
    if migration.get("enabled"):
        for key in ("repo_url", "repo_dist", "key_url", "key_fingerprint",
                    "keyring_path", "sources_path"):
            _require(bool(str(migration[key]).strip()),
                     f"migration.{key} must not be empty when migration is enabled")
        _require(isinstance(migration["apply_to_dists"], list) and len(migration["apply_to_dists"]) > 0,
                 "migration.apply_to_dists must be a non-empty list")
        _require(
            re.fullmatch(r'[0-9a-fA-F]{40}', str(migration["key_fingerprint"])),
            "migration.key_fingerprint must be exactly 40 hex characters"
        )
        _int_in(migration["pin_priority"], 1, 1000, "migration.pin_priority")
        _require(isinstance(migration["prereq_packages"], list),
                 "migration.prereq_packages must be a list")
        uc = migration.get("upgrade_command")
        _require("{package}" in str(uc), "migration.upgrade_command must contain {package}")


# ---------------------------------------------------------------------------
# Provider config validation
# ---------------------------------------------------------------------------

def _validate_provider_config(data: dict[str, Any]) -> None:
    _require(data["apiVersion"] == "fleet-upgrade-provider/v1",
             "apiVersion must be fleet-upgrade-provider/v1")

    provider = data["provider"]
    _require(bool(str(provider["name"]).strip()), "provider.name must not be empty")
    _require(bool(str(provider["cli_binary"]).strip()), "provider.cli_binary must not be empty")
    _require(bool(str(provider["auth_check"]).strip()), "provider.auth_check must not be empty")
    _require(bool(str(provider["discover_command"]).strip()),
             "provider.discover_command must not be empty")
    _require(
        provider["output_format"] in {"json", "csv", "text"},
        "provider.output_format must be json, csv, or text"
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class Config:
    """Parsed configuration container."""

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
    def provider(self) -> dict[str, Any]:
        return self.data["provider"]


def load_tool_config(root: str | os.PathLike[str], tool_name: str) -> Config:
    """Load and validate a tool config from ``.specific/{tool_name}.yaml``."""
    root_path = Path(root).expanduser().resolve()
    path = (root_path / ".specific" / f"{tool_name}.yaml").resolve()
    if not path.is_file():
        raise ConfigError(f"tool config not found: {path} (run 'fleet.py config --init --type tool --name {tool_name}')")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    _check_unknown(raw, _TOOL_ALLOWED, "")
    data = _deep_merge(TOOL_DEFAULTS, raw)
    _validate_tool_config(data)
    return Config(root_path, path, data)


def load_provider_config(root: str | os.PathLike[str], provider_name: str) -> Config:
    """Load and validate a provider config from ``.specific/{provider_name}.yaml``."""
    root_path = Path(root).expanduser().resolve()
    path = (root_path / ".specific" / f"{provider_name}.yaml").resolve()
    if not path.is_file():
        raise ConfigError(f"provider config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    _check_unknown(raw, _PROVIDER_ALLOWED, "")
    data = _deep_merge(PROVIDER_DEFAULTS, raw)
    _validate_provider_config(data)
    return Config(root_path, path, data)


def list_tools(root: str | os.PathLike[str]) -> list[str]:
    """Scan ``.specific/*.yaml`` for files with apiVersion ``fleet-upgrade-tool/v1``."""
    root_path = Path(root).expanduser().resolve()
    specific_dir = root_path / ".specific"
    if not specific_dir.is_dir():
        return []
    tools: list[str] = []
    for yaml_path in sorted(specific_dir.iterdir()):
        if yaml_path.suffix not in (".yaml", ".yml"):
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                continue
            if raw.get("apiVersion") == "fleet-upgrade-tool/v1":
                name = raw.get("tool", {}).get("name")
                if name:
                    tools.append(name)
        except Exception:
            continue
    return tools


# ---------------------------------------------------------------------------
# SSH env helper (T011)
# ---------------------------------------------------------------------------

def load_ssh_env(env_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read ``.personal/ssh.env`` and return parsed credential dict.

    Validates port range, resolves relative key paths, warns on insecure mode.
    """
    path = Path(env_path).expanduser()
    if not path.is_file():
        raise PreflightError(f"SSH env file missing: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")

    missing = [k for k in ("SSH_USER", "SSH_KEY", "SSH_PORT") if not values.get(k)]
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
