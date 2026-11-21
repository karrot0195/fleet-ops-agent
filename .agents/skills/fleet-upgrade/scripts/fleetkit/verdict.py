"""Verdict computation — determine upgrade status per VM+tool."""

from __future__ import annotations

import re
from typing import Any


class VerdictError(Exception):
    exit_code = 3


# Possible verdict values
SKIP = "SKIP"
UP_TO_DATE = "UP-TO-DATE"
UPGRADE = "UPGRADE"
BLOCKED = "BLOCKED"
UNREACHABLE = "UNREACHABLE"


def compute_verdict(
    tool_config: dict[str, Any],
    ssh_result: dict[str, Any],
) -> str:
    """Compute a verdict based on tool config and SSH command results.

    Parameters
    ----------
    tool_config : dict
        A parsed tool config dict (from ``load_tool_config``).
    ssh_result : dict
        Keys expected:
        - ``installed_version`` (str | None) — version returned by ``tool.version_query``
        - ``candidate_version`` (str | None) — available upgrade version
        - ``precheck_ok`` (bool) — did ``tool.precheck`` succeed?
        - ``origin_ok`` (bool) — does package origin match allowlist?
        - ``hold_detected`` (bool) — is there a package hold?
        - ``unreachable`` (bool) — was SSH connection attempted?
        - ``error`` (str | None) — error message if applicable

    Returns
    -------
    One of: SKIP, UP-TO-DATE, UPGRADE, BLOCKED(reason), UNREACHABLE(reason)
    """
    # If SSH failed entirely
    if ssh_result.get("unreachable"):
        reason = ssh_result.get("error", "connection failed after retry")
        return f"{UNREACHABLE}({reason})"

    installed = ssh_result.get("installed_version")

    # Tool not installed at all
    if not installed or not str(installed).strip():
        return SKIP

    # Precheck failure blocks
    if not ssh_result.get("precheck_ok"):
        return f"{BLOCKED}(precheck failed)"

    # Package hold detected
    if ssh_result.get("hold_detected"):
        return f"{BLOCKED}(package held)"

    # Origin mismatch
    if not ssh_result.get("origin_ok"):
        return f"{BLOCKED}(unexpected origin)"

    candidate = ssh_result.get("candidate_version")

    # No candidate means nothing new to install
    if not candidate or not str(candidate).strip():
        return UP_TO_DATE

    # Installed already matches candidate
    if str(installed).strip() == str(candidate).strip():
        return UP_TO_DATE

    return UPGRADE
