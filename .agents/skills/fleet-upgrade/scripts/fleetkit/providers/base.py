"""Abstract base class for discovery providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DiscoveryError(Exception):
    """Raised when a provider discovers incorrectly or encounters errors."""
    exit_code = 4


class ProviderBase(ABC):
    """Base class for fleet discovery providers.

    Sub-classes implement three methods:
    - validate(): ensure CLI binary is installed and authenticated.
    - discover(): fetch current fleet inventory as list[{name, ip, status}].
    - reconcile(previous, current): compute added/removed IPs.
    """

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
            List of VM entries, each with keys: name, ip, status.

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
