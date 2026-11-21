#!/usr/bin/env python3
"""fleet-upgrade — Common Fleet Upgrade Skill CLI.

Usage:
    fleet.py <command> [options]

Commands:
    config      Initialize tool or provider configuration files.
    doctor      Check provider CLI availability and authentication.
    discover    Fetch fleet inventory from a registered provider.
    survey      Run read-only audit across all VMs.
    summary     Show grouped survey results.
    execute     Run canary or fleet upgrade rollout.
    gate        Record canary gate decision.
    rollback    Rollback a single VM to its pre-upgrade state.
    report      Generate and optionally write reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleetkit.cli import main


if __name__ == "__main__":
    sys.exit(main())
