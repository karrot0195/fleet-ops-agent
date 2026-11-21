"""Provider registry and base class for fleet discovery providers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .base import ProviderBase, DiscoveryError


def load_provider(root: str | os.PathLike[str], provider_name: str) -> ProviderBase:
    """Load a provider config and instantiate the matching provider class.

    Providers are mapped by name; only built-in providers are loaded automatically.
    Custom providers require a config file but may need manual registration.
    """
    root_path = Path(root).expanduser().resolve()
    cfg_path = root_path / ".specific" / f"{provider_name}.yaml"
    if not cfg_path.is_file():
        raise DiscoveryError(f"provider config not found: {cfg_path}")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise DiscoveryError(f"{cfg_path} must contain a YAML mapping")

    api_version = raw.get("apiVersion")
    if api_version != "fleet-upgrade-provider/v1":
        raise DiscoveryError(f"unsupported provider apiVersion {api_version!r}")

    from .doctl import DoctlProvider
    from .vultr import VultrProvider
    from .manual import ManualProvider

    # Map provider names to classes
    name_map = {
        "doctl": DoctlProvider,
        "vultr": VultrProvider,
        "vultr-cli": VultrProvider,
        "manual": ManualProvider,
    }

    pclass = name_map.get(provider_name)
    if pclass is None:
        raise DiscoveryError(f"unknown provider '{provider_name}' — use doctl, vultr, or manual")

    return pclass(root)


def list_providers(root: str | os.PathLike[str]) -> list[str]:
    """Scan ``.specific/*.yaml`` for provider configs (apiVersion ``fleet-upgrade-provider/v1``)."""
    root_path = Path(root).expanduser().resolve()
    specific_dir = root_path / ".specific"
    if not specific_dir.is_dir():
        return []
    providers: list[str] = []
    for yaml_path in sorted(specific_dir.iterdir()):
        if yaml_path.suffix not in (".yaml", ".yml"):
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                continue
            if raw.get("apiVersion") == "fleet-upgrade-provider/v1":
                name = raw.get("provider", {}).get("name")
                if name:
                    providers.append(name)
        except Exception:
            continue
    return providers
