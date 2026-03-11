"""
apps.server.main — FastAPI application entry point.

Run with: uvicorn apps.server.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.server.websocket import manager
from apps.tool_marketplace import routes as marketplace
from apps.trip_planner.routes import (
    action_router,
    contract_router,
    demo_router,
    vote_router,
)

# Frontend dist directory (built by Vite)
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize demo state on startup."""
    yield


app = FastAPI(
    title="Vincul Demo",
    description="Demo backend for the Vincul Protocol — 8-friends-trip scenario",
    version="0.1.0",
    lifespan=lifespan,
)

# Include route modules
app.include_router(demo_router)
app.include_router(contract_router)
app.include_router(action_router)
app.include_router(vote_router)
app.include_router(marketplace.router)


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
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
            "name": "Vincul Demo",
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
