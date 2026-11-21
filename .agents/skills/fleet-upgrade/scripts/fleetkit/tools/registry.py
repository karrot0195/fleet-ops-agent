"""Tool configuration loading, validation, and management."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


class ToolConfigError(Exception):
    """Raised when a tool configuration is invalid."""
    exit_code = 2


_REQUIRED_TOOL_FIELDS = [
    "name", "package", "service", "config_paths",
    "version_query", "precheck",
]

_MIGRATION_REQUIRED_IF_ENABLED = [
    "repo_url", "repo_dist", "key_url", "key_fingerprint",
    "keyring_path", "sources_path",
]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolConfigError(message)


def _int_in(value: Any, low: int, high: int, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    _require(low <= value <= high, f"{label} must be between {low} and {high}")
    return value


def validate_tool_config(data: dict[str, Any]) -> None:
    """Validate a parsed tool config dict against the ``fleet-upgrade-tool/v1`` schema.

    Raises ``ToolConfigError`` on any validation failure.
    """
    _require(data.get("apiVersion") == "fleet-upgrade-tool/v1",
             "apiVersion must be fleet-upgrade-tool/v1")

    tool = data.get("tool", {})
    for key in _REQUIRED_TOOL_FIELDS:
        _require(
            key in tool and tool[key] is not None and str(tool[key]).strip(),
            f"tool.{key} is required and must not be empty"
        )

    # config_paths must be a non-empty list
    cp = tool.get("config_paths")
    _require(isinstance(cp, list) and len(cp) > 0, "tool.config_paths must be a non-empty list")

    allowed_origin = tool.get("allowed_origin_patterns", [])
    _require(isinstance(allowed_origin, list), "tool.allowed_origin_patterns must be a list")
    hold_pats = tool.get("hold_patterns", [])
    _require(isinstance(hold_pats, list), "tool.hold_patterns must be a list")
    drift_pats = tool.get("drift_patterns", [])
    _require(isinstance(drift_pats, list), "tool.drift_patterns must be a list")

    verify = tool.get("verify", {})
    for proto in ("http", "https"):
        block = verify.get(proto, {})
        enabled = block.get("enabled")
        if enabled and enabled is not False and enabled != "auto":
            _require(bool(str(block.get("url", "")).strip()),
                     f"tool.verify.{proto}.url required when enabled")
            timeout = block.get("timeout", 10)
            _int_in(timeout, 1, 60, f"tool.verify.{proto}.timeout")

    https_enabled = verify.get("https", {}).get("enabled", "auto")
    _require(https_enabled in {"auto", True, False},
             "tool.verify.https.enabled must be auto, true, or false")
    require_status = verify.get("require_status", [])
    _require(isinstance(require_status, list), "tool.verify.require_status must be a list")

    migration = data.get("migration", {})
    if migration.get("enabled"):
        for key in _MIGRATION_REQUIRED_IF_ENABLED:
            val = migration.get(key)
            _require(val is not None and str(val).strip(),
                     f"migration.{key} is required when migration.enabled is true")
        atd = migration.get("apply_to_dists")
        _require(isinstance(atd, list) and len(atd) > 0,
                 "migration.apply_to_dists must be a non-empty list when migration.enabled is true")
        fp = str(migration.get("key_fingerprint", ""))
        _require(re.fullmatch(r'[0-9a-fA-F]{40}', fp),
                 "migration.key_fingerprint must be exactly 40 hex characters")
        _int_in(migration.get("pin_priority", 0), 1, 1000, "migration.pin_priority")
        prereqs = migration.get("prereq_packages", [])
        _require(isinstance(prereqs, list), "migration.prereq_packages must be a list")
        uc = migration.get("upgrade_command", "")
        _require("{package}" in str(uc), "migration.upgrade_command must contain {package}")


def load_tool_config(root: str | os.PathLike[str], tool_name: str) -> dict[str, Any]:
    """Load, validate, and return a tool config from ``.specific/{tool_name}.yaml``."""
    root_path = Path(root).expanduser().resolve()
    path = root_path / ".specific" / f"{tool_name}.yaml"
    if not path.is_file():
        raise ToolConfigError(f"tool config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ToolConfigError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ToolConfigError(f"{path} must contain a YAML mapping")
    validate_tool_config(raw)
    return raw


def list_tools(root: str | os.PathLike[str]) -> list[str]:
    """Scan ``.specific/*.yaml`` for tool configs (apiVersion ``fleet-upgrade-tool/v1``).

    Returns sorted list of unique tool names.
    """
    root_path = Path(root).expanduser().resolve()
    specific_dir = root_path / ".specific"
    if not specific_dir.is_dir():
        return []
    seen: set[str] = set()
    tools: list[str] = []
    for yaml_path in sorted(specific_dir.iterdir()):
        if yaml_path.suffix not in (".yaml", ".yml"):
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            if raw.get("apiVersion") == "fleet-upgrade-tool/v1":
                name = (raw.get("tool") or {}).get("name")
                if name and name not in seen:
                    seen.add(name)
                    tools.append(name)
        except Exception:
            continue
    return tools
