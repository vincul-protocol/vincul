"""
apps.tool_marketplace.routes — Cross-vendor tool marketplace demo endpoints.

6 endpoints driving the marketplace scenario step by step.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.server.broadcast import receipt_to_event
from apps.server.websocket import manager
from apps.tool_marketplace.state import marketplace_state
from apps.trip_planner.state import demo_state

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── Request models ───────────────────────────────────────────

class InvokeRequest(BaseModel):
    item_id: str
    quantity: int
    shipping_zip: str = "10001"


# ── Step 1: Setup vendors ───────────────────────────────────

@router.post("/setup")
async def setup_vendors():
    """Register 3 vendors, create tool provider with manifest."""
    result = marketplace_state.setup_vendors()
    await manager.broadcast({
        "event_type": "marketplace_setup",
        "status": result["status"],
    })
    return result


# ── Step 2: Create contract ─────────────────────────────────

@router.post("/contract")
async def create_contract():
    """Create and activate the coalition contract."""
    try:
        result = marketplace_state.create_contract()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await manager.broadcast({
        "event_type": "marketplace_contract",
        "status": result["status"],
        "contract_id": result.get("contract_id"),
    })
    return result


# ── Step 3: Create scope DAG ────────────────────────────────

@router.post("/scope")
async def create_scopes():
    """Build root->mid->leaf scope DAG with delegation receipts."""
    try:
        result = marketplace_state.create_scopes()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await manager.broadcast({
        "event_type": "marketplace_scopes",
        "status": result["status"],
        "scope_count": len(result.get("scopes", [])),
    })
    return result


# ── Step 4: Invoke tool ─────────────────────────────────────

@router.post("/invoke")
async def invoke_tool(req: InvokeRequest):
    """Invoke the tool through the agent. Outcome depends on state and params."""
    try:
        result = marketplace_state.invoke(
            item_id=req.item_id,
            quantity=req.quantity,
            shipping_zip=req.shipping_zip,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    summary = (
        f"order {result['payload']['order_id']}" if result["success"]
        else f"denied: {result.get('failure_code', 'UNKNOWN')}"
    )
    await manager.broadcast({
        "event_type": "marketplace_invoke",
        "success": result["success"],
        "summary": summary,
    })
    return result


# ── Step 5: Revoke ──────────────────────────────────────────

@router.post("/revoke")
async def revoke_scope():
    """Revoke mid scope with BFS cascade to leaf."""
    try:
        result = marketplace_state.revoke()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await manager.broadcast({
        "event_type": "marketplace_revoke",
        "status": result["status"],
        "revoked_count": len(result.get("revoked_scope_ids", [])),
    })
    return result


# ── Step 6: Audit trail ─────────────────────────────────────

@router.get("/audit")
async def audit_trail():
    """Full receipt timeline with hash verification."""
    try:
        return marketplace_state.audit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Reset ────────────────────────────────────────────────────

@router.post("/reset")
async def reset_marketplace():
    """Reset marketplace demo and trip demo to clean state."""
    result = marketplace_state.reset()
    demo_state.reset()
    await manager.broadcast({
        "event_type": "marketplace_reset",
    })
    return result
