"""
apps.server.websocket — WebSocket connection manager + /ws endpoint.
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, event: dict) -> None:
        for ws in list(self.active):
            try:
                await ws.send_json(event)
            except Exception:
                self.active.remove(ws)


manager = ConnectionManager()
