"""
Deterministic external service stubs for the trip planner demo.

All connectors are stubs — no network calls.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorResult:
    """Result returned by a connector stub after a booking."""
    external_ref: str
    reversible: bool
    revert_window: str | None
    raw_response: dict


class FlightsConnector:
    """Stub connector for flight bookings. Non-revertable."""

    def book(self, resource: str, params: dict) -> ConnectorResult:
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
        raise ValueError(f"Flight booking {ref!r} is non-revertable.")


class HotelsConnector:
    """Stub connector for hotel bookings. Revertable within 24 hours."""

    def book(self, resource: str, params: dict) -> ConnectorResult:
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
        pass
