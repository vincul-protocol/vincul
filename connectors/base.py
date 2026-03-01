"""
connectors.base — Shared types for connector stubs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorResult:
    """Result returned by a connector stub after a booking."""
    external_ref: str
    reversible: bool
    revert_window: str | None
    raw_response: dict
