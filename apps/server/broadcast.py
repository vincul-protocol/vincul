"""
apps.server.broadcast — Receipt → WebSocket event conversion.
"""

from __future__ import annotations

from pact.receipts import Receipt


def receipt_to_event(receipt: Receipt, summary: str = "") -> dict:
    """Convert a Receipt to a WebSocket-friendly event dict."""
    return {
        "event_type": "receipt",
        "receipt_kind": receipt.receipt_kind.value,
        "receipt_hash": receipt.receipt_hash,
        "issued_at": receipt.issued_at,
        "initiated_by": receipt.initiated_by,
        "outcome": receipt.outcome,
        "summary": summary,
        "detail": receipt.detail,
        "scope_id": receipt.scope_id,
    }
