# Contract: Provider Interface

**Version**: 1.0 | **Status**: Draft

## Overview

Discovery providers implement a Python class that exposes three methods for fleet inventory management. Providers are registered via `.specific/{provider}.yaml` configuration files.

## Interface

```python
from abc import ABC, abstractmethod
from typing import Any

class ProviderBase(ABC):
    """Base class for fleet discovery providers."""

    @abstractmethod
    def validate(self) -> bool:
        """Check that the provider CLI is installed and authenticated.

        Returns:
            True if validation passes.

        Raises:
            DiscoveryError: If validation fails, with a descriptive message.
        """
        ...

    @abstractmethod
    def discover(self) -> list[dict[str, str]]:
        """Fetch the current fleet inventory from the provider.

        Returns:
            List of VM entries, each with keys:
            - name: str (VM hostname/label)
            - ip: str (IPv4 address)
            - status: str ("active", "inactive", "unknown")

        Raises:
            DiscoveryError: If discovery fails.
        """
        ...

    @abstractmethod
    def reconcile(
        self,
        previous: list[dict[str, Any]],
        current: list[dict[str, str]]
    ) -> tuple[list[str], list[str]]:
        """Compute added and removed IPs between inventory snapshots.

        Args:
            previous: Previous inventory entries (from state.json).
            current: Current inventory entries (from discover()).

        Returns:
            Tuple of (added_ips, removed_ips).
        """
        ...
```

## Registration

Providers are registered by creating `.specific/{provider}.yaml`:

```yaml
apiVersion: fleet-upgrade-provider/v1
provider:
  name: doctl
  cli_binary: doctl
  auth_check: "doctl auth list"
  discover_command: "doctl compute droplet list --output json"
  output_format: json
  ip_field: "networks.v4[?type=='public'].ip_address[0]"
  name_field: name
```

## Built-in Providers

| Provider | CLI Binary | Auth Check | Discovery Command |
|----------|------------|------------|-------------------|
| doctl | `doctl` | `doctl auth list` | `doctl compute droplet list --output json` |
| vultr-cli | `vultr-cli` | `vultr-cli account` | `vultr-cli instances --json` |
| manual | N/A | N/A | Reads from `ip.txt` or specified file |

## Output Format

### JSON (doctl, vultr-cli)

Provider must return a JSON array of objects. Each object must have fields mappable to `name` and `ip`.

Example (doctl):
```json
[
  {
    "name": "web-01",
    "status": "active",
    "networks": {
      "v4": [
        {"type": "public", "ip_address": "192.0.2.1"}
      ]
    }
  }
]
```

### Text (manual)

Manual provider reads a CSV file with format:
```
Name,IP
web-01,192.0.2.1
web-02,192.0.2.2
```

## Error Handling

| Error | Behavior |
|-------|----------|
| CLI binary not found | `DiscoveryError` with message naming the missing binary |
| Auth check fails | `DiscoveryError` with auth error output |
| Discovery command times out | `DiscoveryError` after configured timeout (default 60s) |
| Output unparseable | `DiscoveryError` with parse error details |
| No active VMs found | Returns empty list (not an error) |

## Extension Points

New providers can be added by:
1. Creating `.specific/{provider}.yaml` with the provider config.
2. Implementing a Python class in `fleetkit/providers/{provider}.py` that extends `ProviderBase`.
3. Registering the class in `fleetkit/providers/__init__.py`.

No changes to the core skill are required.
