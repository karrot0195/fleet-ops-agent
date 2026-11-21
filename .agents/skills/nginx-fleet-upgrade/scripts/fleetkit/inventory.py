from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from .state import utcnow


class DiscoveryError(Exception):
    exit_code = 5


def validate_ip(ip: str) -> str:
    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError as exc:
        raise DiscoveryError(f"invalid IPv4 address: {ip}") from exc
    return ip


def parse_ip_file(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            raise DiscoveryError(f"ip.txt line {number}: expected Name,IP")
        name, ip = (part.strip() for part in line.split(",", 1))
        if not name:
            raise DiscoveryError(f"ip.txt line {number}: empty name")
        validate_ip(ip)
        if ip in seen:
            continue
        seen.add(ip)
        entries.append({"name": name, "ip": ip, "status": "active"})
    return sorted(entries, key=lambda item: item["name"].lower())


def render_ip_file(entries: list[dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item["name"].lower())
    return "".join(f"{entry['name']},{entry['ip']}\n" for entry in ordered)


def write_ip_file(path: str | Path, entries: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_ip_file(entries), encoding="utf-8")


def parse_doctl_json(text: str) -> list[dict[str, str]]:
    try:
        droplets = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"cannot parse doctl output: {exc}") from exc
    if not isinstance(droplets, list):
        raise DiscoveryError("doctl output was not a JSON list")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for droplet in droplets:
        if not isinstance(droplet, dict) or droplet.get("status") != "active":
            continue
        name = str(droplet.get("name") or "").strip()
        if not name:
            continue
        public_ip = None
        for network in (droplet.get("networks") or {}).get("v4", []) or []:
            if network.get("type") == "public" and network.get("ip_address"):
                public_ip = network["ip_address"]
                break
        if not public_ip:
            continue
        validate_ip(public_ip)
        if public_ip in seen:
            continue
        seen.add(public_ip)
        entries.append({"name": name, "ip": public_ip, "status": "active"})
    return sorted(entries, key=lambda item: item["name"].lower())


def doctl_runner(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def discover_from_doctl(runner: Callable[..., Any] | None = None, timeout: int = 60) -> list[dict[str, str]]:
    call = runner or doctl_runner
    try:
        completed = call(["doctl", "compute", "droplet", "list", "--output", "json"], timeout)
    except FileNotFoundError as exc:
        raise DiscoveryError("doctl executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiscoveryError("doctl timed out") from exc
    if completed.returncode != 0:
        raise DiscoveryError(f"doctl failed: {(completed.stderr or '').strip()}")
    return parse_doctl_json(completed.stdout or "")


def discover_from_file(path: str | Path) -> list[dict[str, str]]:
    target = Path(path)
    if not target.is_file():
        raise DiscoveryError(f"inventory file not found: {target}")
    return parse_ip_file(target.read_text(encoding="utf-8"))


def reconcile(state_data: dict[str, Any], entries: list[dict[str, str]], source: str) -> tuple[list[str], list[str]]:
    now = utcnow()
    previous = state_data["inventory"].get("entries", [])
    first_seen = {entry["ip"]: entry.get("first_seen") or now for entry in previous}
    by_ip: dict[str, dict[str, Any]] = {}
    for entry in entries:
        ip = entry["ip"]
        by_ip[ip] = {
            "name": entry["name"],
            "ip": ip,
            "status": entry.get("status", "active"),
            "first_seen": first_seen.get(ip, now),
            "last_seen": now,
        }
    current = sorted(by_ip.values(), key=lambda item: (item["name"].lower(), item["ip"]))
    current_ips = {entry["ip"] for entry in current}
    previous_ips = {entry["ip"] for entry in previous}
    added = sorted(current_ips - previous_ips)
    removed = sorted(previous_ips - current_ips)
    for ip in removed:
        state_data["records"].pop(ip, None)
    state_data["inventory"] = {
        "captured_at": now,
        "source": source,
        "entries": current,
        "added": added,
        "removed": removed,
    }
    return added, removed
