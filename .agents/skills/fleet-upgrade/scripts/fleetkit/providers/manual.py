"""Manual provider — reads inventory from a CSV file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import ProviderBase, DiscoveryError


def _validate_ipv4(ip: str) -> bool:
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            num = int(part)
            if not 0 <= num <= 255:
                return False
        except ValueError:
            return False
    return True


# Strict IPv4 regex for quick validation
_IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def _is_valid_ip(ip: str) -> bool:
    m = _IP_RE.match(ip.strip())
    if not m:
        return False
    return all(0 <= int(g) <= 255 for g in m.groups())


class ManualProvider(ProviderBase):
    """Read inventory from a CSV file with Name,IP header."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def validate(self) -> bool:
        inventory_path = self.root / "ip.txt"
        if not inventory_path.is_file():
            raise DiscoveryError("ip.txt not found; manual provider requires an inventory file")
        return True

    def discover(self) -> list[dict[str, str]]:
        inventory_path = self.root / "ip.txt"
        if not inventory_path.is_file():
            raise DiscoveryError("ip.txt not found; manual provider requires an inventory file")

        entries: list[dict[str, str]] = []
        seen: set[str] = set()

        for line_num, raw_line in enumerate(inventory_path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("name,ip") or stripped.lower().startswith("name , ip"):
                continue  # skip header
            parts = [p.strip() for p in stripped.split(",")]
            if len(parts) < 2:
                continue  # skip malformed lines
            name, ip = parts[0], parts[1]
            if not _is_valid_ip(ip):
                continue  # skip invalid IPs
            if ip in seen:
                continue  # deduplicate
            seen.add(ip)
            entries.append({"name": name, "ip": ip, "status": "active"})
        return entries

    def reconcile(
        self,
        previous: list[dict[str, Any]],
        current: list[dict[str, str]]
    ) -> tuple[list[str], list[str]]:
        prev_ips = {e.get("ip", "") for e in previous}
        curr_ips = {e.get("ip", "") for e in current}
        return sorted(curr_ips - prev_ips), sorted(prev_ips - curr_ips)
