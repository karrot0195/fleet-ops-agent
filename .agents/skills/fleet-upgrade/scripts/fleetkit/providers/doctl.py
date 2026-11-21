"""DigitalOcean provider using doctl CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .base import ProviderBase, DiscoveryError


class DoctlProvider(ProviderBase):
    """Discover VMs via `doctl compute droplet list --output json`."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def validate(self) -> bool:
        result = subprocess.run(
            ["doctl", "auth", "list"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise DiscoveryError("doctl auth check failed: {}".format(result.stderr.strip()))
        # Check we have at least one active context
        outputs = [line for line in result.stdout.splitlines() if not line.startswith("*")]
        if not outputs:
            raise DiscoveryError("no active doctl authentication context found")
        return True

    def discover(self) -> list[dict[str, str]]:
        result = subprocess.run(
            ["doctl", "compute", "droplet", "list", "--output", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise DiscoveryError("doctl discover failed: {}".format(result.stderr.strip()))
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"invalid JSON from doctl: {exc}") from exc

        entries: list[dict[str, str]] = []
        for droplet in data:
            name = droplet.get("name", "")
            status = droplet.get("status", "unknown")
            ip = ""
            networks = droplet.get("networks", {})
            v4_list = networks.get("v4", [])
            for addr_info in v4_list:
                if addr_info.get("type") == "public":
                    ip = addr_info.get("ip_address", "")
                    break
            if ip:
                entries.append({"name": name, "ip": ip, "status": status})
        return entries

    def reconcile(
        self,
        previous: list[dict[str, Any]],
        current: list[dict[str, str]]
    ) -> tuple[list[str], list[str]]:
        prev_ips = {e.get("ip", "") for e in previous}
        curr_ips = {e.get("ip", "") for e in current}
        return sorted(curr_ips - prev_ips), sorted(prev_ips - curr_ips)
