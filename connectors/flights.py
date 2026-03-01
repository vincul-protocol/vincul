"""
connectors.flights — Deterministic flight booking stub.

Generates a stable reference from the resource string.
Flights are non-revertable.
"""

from __future__ import annotations

import hashlib

from connectors.base import ConnectorResult


class FlightsConnector:
    """Stub connector for flight bookings. No network calls."""

    def book(self, resource: str, params: dict) -> ConnectorResult:
        """Book a flight. Returns a deterministic reference."""
        # Deterministic ref from resource hash
        digest = hashlib.sha256(resource.encode()).hexdigest()[:4].upper()
        ref = f"BA-{digest}"

        return ConnectorResult(
            external_ref=ref,
            reversible=False,
            revert_window=None,
            raw_response={
                "status": "confirmed",
                "booking_ref": ref,
                "resource": resource,
                "params": params,
            },
        )

    def revert(self, ref: str) -> None:
        """Flights are non-revertable."""
        raise ValueError(f"Flight booking {ref!r} is non-revertable.")
