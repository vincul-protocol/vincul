"""
apps.server.main — FastAPI application entry point.

Run with: uvicorn apps.server.main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.server.demo_state import demo_state
from apps.server.routes import actions, contract, demo, votes
from apps.server.websocket import manager

# Frontend dist directory (built by Vite)
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize demo state on startup."""
    # Could pre-setup here, but we let the user call /contract/setup explicitly
    yield


app = FastAPI(
    title="Pact Demo",
    description="Demo backend for the Pact Protocol — 8-friends-trip scenario",
    version="0.1.0",
    lifespan=lifespan,
)

# Include route modules
app.include_router(demo.router)
app.include_router(contract.router)
app.include_router(actions.router)
app.include_router(votes.router)


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; we only broadcast from server side
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Serve built frontend if dist exists
if _WEB_DIST.is_dir():
    _ASSETS = _WEB_DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for any unmatched route."""
        return FileResponse(str(_WEB_DIST / "index.html"))
else:
    @app.get("/")
    async def root():
        return {
            "name": "Pact Demo",
            "version": "0.1.0",
            "endpoints": [
                "POST /contract/setup",
                "POST /contract/dissolve",
                "POST /action",
                "POST /vote/open",
                "POST /vote/cast",
                "POST /demo/reset",
                "GET  /demo/status",
                "WS   /ws",
            ],
        }
