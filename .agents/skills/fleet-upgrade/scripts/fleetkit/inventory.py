"""Provider-agnostic inventory reconciliation and IP file I/O."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class InventoryError(Exception):
    exit_code = 3


# IPv4 validation regex
_IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def validate_ip(ip: str) -> str:
    """Validate an IPv4 address string. Returns the normalized string or raises."""
    m = _IPV4_RE.match(ip.strip())
    if not m:
        raise InventoryError(f"invalid IPv4 address: {ip!r}")
    if any(int(g) > 255 for g in m.groups()):
        raise InventoryError(f"invalid IPv4 octet in: {ip!r}")
    return ip.strip()


def parse_ip_file(path: str | Path) -> list[dict[str, str]]:
    """Parse a CSV file with Name,IP header into a list of VM entry dicts.

    Skips empty lines, comments (#), and invalid IPs. Deduplicates by IP.
    """
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    ip_file = Path(path)
    if not ip_file.is_file():
        return entries

    for raw_line in ip_file.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("name,ip"):
            continue  # skip header

        parts = [p.strip() for p in stripped.split(",")]
        if len(parts) < 2:
            continue

        name = parts[0]
        ip = parts[1]
        try:
            validate_ip(ip)
        except InventoryError:
            continue

        if ip in seen:
            continue  # deduplicate
        seen.add(ip)
        entries.append({"name": name, "ip": ip, "status": "active"})

    return entries


def write_ip_file(path: str | Path, entries: list[dict[str, Any]]) -> Path:
    """Write sorted inventory entries to a CSV file (Name,IP)."""
    ip_path = Path(path)
    ip_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_entries = sorted(entries, key=lambda e: e.get("ip", ""))
    lines = ["Name,IP"]
    for e in sorted_entries:
        lines.append(f"{e.get('name', '')},{e['ip']}")
    ip_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ip_path


def reconcile(
    state_data: dict[str, Any],
    entries: list[dict[str, Any]],
    source: str,
) -> tuple[list[str], list[str]]:
    """Compute added/removed IPs between previous inventory and new entries.

    Updates state_data["inventory"] in place.
    Returns (added_ips, removed_ips).
    """
    prev_entries = state_data.get("inventory", {}).get("entries", [])
    prev_ips = {e.get("ip", "") for e in prev_entries}
    curr_ips = {e.get("ip", "") for e in entries}

    added = sorted(curr_ips - prev_ips)
    removed = sorted(prev_ips - curr_ips)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    state_data["inventory"] = {
        "captured_at": now,
        "source": source,
        "entries": entries,
        "added": added,
        "removed": removed,
    }

    return added, removed
