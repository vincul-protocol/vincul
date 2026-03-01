"""
routes.actions — POST /action
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.server.broadcast import receipt_to_event
from apps.server.demo_state import demo_state
from apps.server.websocket import manager

router = APIRouter(tags=["actions"])


class ActionRequest(BaseModel):
    principal: str
    scope_id: str
    action: dict[str, Any]
    budget_amounts: dict[str, str] | None = None


@router.post("/action")
async def perform_action(req: ActionRequest):
    """Execute an action through the Pact enforcement pipeline."""
    if not demo_state.is_setup:
        raise HTTPException(status_code=400, detail="Contract not set up yet.")

    receipt = demo_state.commit_action(
        principal=req.principal,
        scope_id=req.scope_id,
        action=req.action,
        budget_amounts=req.budget_amounts,
    )

    # Build human-readable summary
    ns = req.action.get("namespace", "")
    resource = req.action.get("resource", "")
    if receipt.outcome == "success":
        ext_ref = receipt.detail.get("external_ref", "")
        cost = req.budget_amounts.get("EUR", "") if req.budget_amounts else ""
        summary = f"{req.principal.split(':')[1]} booked {resource}"
        if ext_ref:
            summary += f" ref:{ext_ref}"
        if cost:
            summary += f" · €{cost}"
    else:
        code = receipt.detail.get("error_code", "UNKNOWN")
        summary = f"{req.principal.split(':')[1]} denied: {code}"

    await manager.broadcast(receipt_to_event(receipt, summary))

    return {
        "receipt_kind": receipt.receipt_kind.value,
        "receipt_hash": receipt.receipt_hash,
        "outcome": receipt.outcome,
        "detail": receipt.detail,
        "summary": summary,
    }
