"""
routes.demo — POST /demo/reset, GET /demo/status
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.server.demo_state import demo_state

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/reset")
async def reset_demo():
    """Re-initialize everything to a clean state."""
    return demo_state.reset()


@router.get("/status")
async def demo_status():
    """Return current demo state summary."""
    return demo_state.status_summary()


@router.get("/state")
async def demo_state_full():
    """Return enriched demo state for the frontend."""
    return demo_state.enriched_state()
