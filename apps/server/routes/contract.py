"""
routes.contract — POST /contract/setup, POST /contract/dissolve
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.server.broadcast import receipt_to_event
from apps.server.demo_state import demo_state
from apps.server.websocket import manager

router = APIRouter(prefix="/contract", tags=["contract"])


class DissolveRequest(BaseModel):
    initiated_by: str
    signatures: list[str]


@router.post("/setup")
async def setup_contract():
    """Set up the 8-friends-trip contract with scopes and budgets."""
    result = demo_state.setup_contract()
    await manager.broadcast({
        "event_type": "contract_setup",
        "status": result["status"],
        "contract_id": result.get("contract_id"),
    })
    return result


@router.post("/dissolve")
async def dissolve_contract(req: DissolveRequest):
    """Dissolve the contract and revoke all scopes."""
    if not demo_state.is_setup:
        raise HTTPException(status_code=400, detail="Contract not set up yet.")

    try:
        receipts = demo_state.dissolve(req.initiated_by, req.signatures)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for r in receipts:
        summary = (
            f"{r.receipt_kind.value} by {r.initiated_by}"
        )
        await manager.broadcast(receipt_to_event(r, summary))

    return {
        "status": "dissolved",
        "receipts": [
            {
                "receipt_kind": r.receipt_kind.value,
                "receipt_hash": r.receipt_hash,
                "outcome": r.outcome,
            }
            for r in receipts
        ],
    }
