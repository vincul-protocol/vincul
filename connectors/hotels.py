"""
connectors.hotels — Deterministic hotel booking stub.

Generates a stable reference from the resource string.
Hotels are revertable within 24 hours.
"""

from __future__ import annotations

import hashlib

from connectors.base import ConnectorResult


class HotelsConnector:
    """Stub connector for hotel bookings. No network calls."""

    def book(self, resource: str, params: dict) -> ConnectorResult:
        """Book a hotel. Returns a deterministic reference."""
        digest = hashlib.sha256(resource.encode()).hexdigest()[:5].upper()
        ref = f"HLT-{digest}"

        return ConnectorResult(
            external_ref=ref,
            reversible=True,
            revert_window="PT24H",
            raw_response={
                "status": "confirmed",
                "booking_ref": ref,
                "resource": resource,
                "params": params,
            },
        )

    def revert(self, ref: str) -> None:
        """Revert a hotel booking. Always succeeds (stub)."""
        pass
