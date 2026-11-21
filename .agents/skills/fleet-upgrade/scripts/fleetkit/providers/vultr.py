"""Vultr provider using vultr-cli."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .base import ProviderBase, DiscoveryError


class VultrProvider(ProviderBase):
    """Discover VMs via `vultr-cli instances --json`."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def validate(self) -> bool:
        result = subprocess.run(
            ["vultr-cli", "account"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise DiscoveryError("vultr-cli auth check failed: {}".format(result.stderr.strip()))
        return True

    def discover(self) -> list[dict[str, str]]:
        result = subprocess.run(
            ["vultr-cli", "instances", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise DiscoveryError("vultr-cli discover failed: {}".format(result.stderr.strip()))
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"invalid JSON from vultr-cli: {exc}") from exc

        entries: list[dict[str, str]] = []
        for instance in data:
            label = instance.get("label", "")
            main_ip = instance.get("main_ip", "")
            status_raw = instance.get("status", "")
            # Map vultr status to our convention
            status_map = {"Active": "active", "Paused": "inactive", "Deleted": "inactive"}
            status = status_map.get(status_raw, "unknown")
            if main_ip:
                entries.append({"name": label, "ip": main_ip, "status": status})
        return entries

    def reconcile(
        self,
        previous: list[dict[str, Any]],
        current: list[dict[str, str]]
    ) -> tuple[list[str], list[str]]:
        prev_ips = {e.get("ip", "") for e in previous}
        curr_ips = {e.get("ip", "") for e in current}
        return sorted(curr_ips - prev_ips), sorted(prev_ips - curr_ips)
