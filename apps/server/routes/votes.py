"""
routes.votes — POST /vote/open, POST /vote/cast
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.server.broadcast import receipt_to_event
from apps.server.demo_state import demo_state
from apps.server.websocket import manager

router = APIRouter(prefix="/vote", tags=["votes"])


class OpenVoteRequest(BaseModel):
    scope_id: str
    request: str
    requested_types: list[str]
    requested_ceiling: str


class CastVoteRequest(BaseModel):
    vote_id: str
    principal: str


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


@router.post("/open")
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


@router.post("/cast")
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
