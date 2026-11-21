from __future__ import annotations

import fnmatch
import re
from typing import Any


SKIP = "SKIP"
UP_TO_DATE = "UP-TO-DATE"
UPGRADE = "UPGRADE"
BLOCKED = "BLOCKED"
UNREACHABLE = "UNREACHABLE"

VERDICTS = (SKIP, UP_TO_DATE, UPGRADE, BLOCKED, UNREACHABLE)


def _order(char: str) -> int:
    if char.isdigit():
        return 0
    if char.isalpha():
        return ord(char)
    if char == "~":
        return -1
    if char:
        return ord(char) + 256
    return 0


def _verrevcmp(left: str, right: str) -> int:
    i = j = 0
    while i < len(left) or j < len(right):
        first_diff = 0
        while (i < len(left) and not left[i].isdigit()) or (j < len(right) and not right[j].isdigit()):
            lc = _order(left[i]) if i < len(left) and not left[i].isdigit() else 0
            rc = _order(right[j]) if j < len(right) and not right[j].isdigit() else 0
            if lc != rc:
                return lc - rc
            if i < len(left) and not left[i].isdigit():
                i += 1
            if j < len(right) and not right[j].isdigit():
                j += 1
        while i < len(left) and left[i] == "0":
            i += 1
        while j < len(right) and right[j] == "0":
            j += 1
        while i < len(left) and j < len(right) and left[i].isdigit() and right[j].isdigit():
            if not first_diff:
                first_diff = ord(left[i]) - ord(right[j])
            i += 1
            j += 1
        if i < len(left) and left[i].isdigit():
            return 1
        if j < len(right) and right[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _split_version(version: str) -> tuple[int, str, str]:
    epoch = 0
    rest = version
    if ":" in version:
        head, tail = version.split(":", 1)
        if head.isdigit():
            epoch = int(head)
            rest = tail
    if "-" in rest:
        upstream, revision = rest.rsplit("-", 1)
    else:
        upstream, revision = rest, ""
    return epoch, upstream, revision


def compare_versions(left: str, right: str) -> int:
    left_epoch, left_upstream, left_revision = _split_version(left)
    right_epoch, right_upstream, right_revision = _split_version(right)
    if left_epoch != right_epoch:
        return 1 if left_epoch > right_epoch else -1
    upstream = _verrevcmp(left_upstream, right_upstream)
    if upstream:
        return 1 if upstream > 0 else -1
    revision = _verrevcmp(left_revision, right_revision)
    if revision:
        return 1 if revision > 0 else -1
    return 0


def _version_table_origin(lines: list[str], *versions: str | None) -> str | None:
    """Return the repository URL of the first version in `versions` that has a table entry.

    The first URL after the '***' line belongs to the INSTALLED version, so the whole
    version table must be walked to find the entry matching the wanted version.
    """
    header_re = re.compile(r"^\s+\*{0,3}\s*(\S+)\s")
    url_re = re.compile(r"https?://\S+")
    wanted = [version for version in versions if version]
    current: str | None = None
    found: dict[str, str] = {}
    for line in lines:
        header = header_re.match(line)
        if header and not url_re.search(line) and not header.group(1).endswith(":"):
            current = header.group(1)
            continue
        url = url_re.search(line)
        if url and current and current not in found:
            found[current] = url.group(0)
    for version in wanted:
        if version in found:
            return found[version]
    return None


def parse_apt_policy(text: str) -> dict[str, Any]:
    installed = None
    candidate = None
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Installed:"):
            value = stripped.split(":", 1)[1].strip()
            installed = value if value and value != "(none)" else None
        elif stripped.startswith("Candidate:"):
            value = stripped.split(":", 1)[1].strip()
            candidate = value if value and value != "(none)" else None
    origin = _version_table_origin(lines, candidate, installed)
    return {"installed": installed, "candidate": candidate, "origin": origin}


def parse_nginx_v(text: str) -> dict[str, list[str]]:
    static = sorted(set(re.findall(r"--with-([A-Za-z0-9_]+)_module\b", text)))
    dynamic = sorted(set(re.findall(r"--add-dynamic-module(?:=|\s+)([^\s]+)", text)))
    return {"static": static, "dynamic": dynamic}


def parse_load_modules(text: str) -> list[str]:
    return sorted(set(re.findall(r"load_module\s+([^;]+);", text)))


def origin_allowed(origin: str | None, patterns: list[str]) -> bool:
    if not origin:
        return False
    lowered = origin.lower()
    return any(pattern.lower() in lowered for pattern in patterns if pattern)


def matching_holds(holds: list[str], patterns: list[str]) -> list[str]:
    matched = []
    for package in holds:
        for pattern in patterns:
            if fnmatch.fnmatchcase(package.lower(), pattern.lower()):
                matched.append(package)
                break
    return matched


def third_party_modules(modules: dict[str, list[str]], allowed_dirs: list[str]) -> list[str]:
    flagged: list[str] = []
    for path in modules.get("dynamic", []):
        if not any(path.startswith(directory.rstrip("/") + "/") or path == directory for directory in allowed_dirs):
            flagged.append(path)
    return sorted(set(flagged))


def decide(evidence: dict[str, Any], cfg: Any) -> tuple[str, str | None]:
    tool = cfg.tool
    if not evidence.get("binary_present") and not evidence.get("installed_version"):
        return SKIP, None

    if not evidence.get("config_test_ok", True):
        return BLOCKED, "configuration test failed"

    held = matching_holds(evidence.get("held_packages", []), tool["hold_patterns"])
    if held:
        return BLOCKED, "package held: " + ", ".join(held)

    if evidence.get("binary_present") and not evidence.get("installed_version"):
        return BLOCKED, "unexpected package source: source build"
    if evidence.get("installed_version") and not origin_allowed(
        evidence.get("package_origin"), tool["allowed_origin_patterns"]
    ):
        return BLOCKED, f"unexpected package source: {evidence.get('package_origin') or 'unknown'}"

    flagged = evidence.get("third_party_modules") or []
    if flagged:
        return BLOCKED, "third-party module requires review: " + ", ".join(flagged)

    installed = evidence.get("installed_version")
    candidate = evidence.get("candidate_version")
    if not candidate:
        return BLOCKED, "no candidate version determined"
    if not installed:
        return BLOCKED, "installed version unknown"
    if compare_versions(installed, candidate) >= 0:
        return UP_TO_DATE, None
    return UPGRADE, None
