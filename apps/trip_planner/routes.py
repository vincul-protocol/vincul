"""
apps.trip_planner.routes — 8-friends trip planner demo endpoints.

Endpoints:
  POST /demo/reset, GET /demo/status, GET /demo/state
  POST /contract/setup, POST /contract/dissolve
  POST /action
  POST /vote/open, POST /vote/cast
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.server.broadcast import receipt_to_event
from apps.server.websocket import manager
from apps.trip_planner.state import demo_state
from vincul.sdk import ToolResult


# ── Routers ──────────────────────────────────────────────────

demo_router = APIRouter(prefix="/demo", tags=["demo"])
contract_router = APIRouter(prefix="/contract", tags=["contract"])
action_router = APIRouter(tags=["actions"])
vote_router = APIRouter(prefix="/vote", tags=["votes"])


# ── Request models ───────────────────────────────────────────

class ActionRequest(BaseModel):
    principal: str
    scope_id: str
    action: dict[str, Any]
    budget_amounts: dict[str, str] | None = None


class DissolveRequest(BaseModel):
    initiated_by: str
    signatures: list[str]


class OpenVoteRequest(BaseModel):
    scope_id: str
    request: str
    requested_types: list[str]
    requested_ceiling: str


class CastVoteRequest(BaseModel):
    vote_id: str
    principal: str


# ── Demo lifecycle ───────────────────────────────────────────

@demo_router.post("/reset")
async def reset_demo():
    """Re-initialize everything to a clean state."""
    return demo_state.reset()


@demo_router.get("/status")
async def demo_status():
    """Return current demo state summary."""
    return demo_state.status_summary()


@demo_router.get("/state")
async def demo_state_full():
    """Return enriched demo state for the frontend."""
    return demo_state.enriched_state()


# ── Contract ─────────────────────────────────────────────────

@contract_router.post("/setup")
async def setup_contract():
    """Set up the 8-friends-trip contract with scopes and budgets."""
    result = demo_state.setup_contract()
    await manager.broadcast({
        "event_type": "contract_setup",
        "status": result["status"],
        "contract_id": result.get("contract_id"),
    })
    return result


@contract_router.post("/dissolve")
async def dissolve_contract(req: DissolveRequest):
    """Dissolve the contract and revoke all scopes."""
    if not demo_state.is_setup:
        raise HTTPException(status_code=400, detail="Contract not set up yet.")

    try:
        receipts = demo_state.dissolve(req.initiated_by, req.signatures)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    for r in receipts:
        summary = f"{r.receipt_kind.value} by {r.initiated_by}"
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


# ── Actions ──────────────────────────────────────────────────

@action_router.post("/action")
async def perform_action(req: ActionRequest):
    """Execute an action through the Vincul enforcement pipeline."""
    if not demo_state.is_setup:
        raise HTTPException(status_code=400, detail="Contract not set up yet.")

    result = demo_state.commit_action(
        principal=req.principal,
        scope_id=req.scope_id,
        action=req.action,
        budget_amounts=req.budget_amounts,
    )

    # Unify ToolResult and Receipt into a common response
    if isinstance(result, ToolResult):
        receipt = result.receipt
        detail = receipt.detail
        if result.success and result.payload:
            detail = {**detail, **result.payload}
    else:
        receipt = result
        detail = receipt.detail

    # Build human-readable summary
    resource = req.action.get("resource", "")
    if receipt.outcome == "success":
        ext_ref = detail.get("external_ref", "")
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
        "detail": detail,
        "summary": summary,
    }


# ── Votes ────────────────────────────────────────────────────

def _session_dict(session) -> dict:
    return {
        "vote_id": session.vote_id,
        "scope_id": session.scope_id,
        "request": session.request,
        "requested_types": session.requested_types,
        "requested_ceiling": session.requested_ceiling,
        "votes_for": session.votes_for,
        "threshold": session.threshold,
        "resolved": session.resolved,
        "new_scope_id": session.new_scope_id,
    }


@vote_router.post("/open")
async def open_vote(req: OpenVoteRequest):
    """Open a governance vote to widen a scope."""
    if not demo_state.is_setup:
        raise HTTPException(status_code=400, detail="Contract not set up yet.")

    session = demo_state.open_vote(
        scope_id=req.scope_id,
        request=req.request,
        requested_types=req.requested_types,
        requested_ceiling=req.requested_ceiling,
    )

    await manager.broadcast({
        "event_type": "vote_opened",
        "vote_id": session.vote_id,
        "scope_id": session.scope_id,
        "request": session.request,
    })

    return _session_dict(session)


@vote_router.post("/cast")
async def cast_vote(req: CastVoteRequest):
    """Cast a vote. Auto-resolves if threshold is met."""
    try:
        session, receipt = demo_state.cast_vote(req.vote_id, req.principal)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await manager.broadcast({
        "event_type": "vote_cast",
        "vote_id": session.vote_id,
        "principal": req.principal,
        "votes_count": len(session.votes_for),
        "resolved": session.resolved,
    })

    if receipt:
        summary = f"Vote passed — new scope {session.new_scope_id} delegated"
        await manager.broadcast(receipt_to_event(receipt, summary))

    result = _session_dict(session)
    if receipt:
        result["delegation_receipt"] = {
            "receipt_kind": receipt.receipt_kind.value,
            "receipt_hash": receipt.receipt_hash,
            "outcome": receipt.outcome,
        }
    return result
