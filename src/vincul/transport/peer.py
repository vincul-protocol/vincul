"""
vincul.transport.peer — VinculPeer: symmetric async WebSocket peer

Each VinculPeer can both listen() and connect(). After the mutual
HELLO handshake, both sides have equal send/receive capabilities.

Security rules:
  - Reject invalid signatures (drop + log)
  - Reject sender_id not in registry (unknown peer)
  - Never auto-accept new pubkey mid-session
  - All failures fail closed
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import websockets
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve as ws_serve

from vincul.identity import KeyPair
from vincul.transport.envelope import (
    MessageEnvelope,
    sign_envelope,
    verify_envelope,
)
from vincul.transport.handshake import (
    HelloMessage,
    sign_hello,
    verify_hello,
    b64_to_pubkey,
)
from vincul.transport.registry import PeerRegistry

logger = logging.getLogger("vincul.transport.peer")


class VinculPeer:
    """
    Symmetric VinculNet peer.

    Can both listen for incoming connections and connect to remote peers.
    After handshake, all connections are equal — both sides can send
    and receive signed messages.
    """

    def __init__(self, my_id: str, keypair: KeyPair) -> None:
        self.my_id = my_id
        self.keypair = keypair
        self.registry = PeerRegistry()
        self._message_handler: Callable[[str, dict], None] | None = None
        self._server: Any = None

    def on_message(self, handler: Callable[[str, dict], None]) -> None:
        """
        Register a callback for verified incoming messages.

        handler(sender_id: str, payload: dict) -> None
        """
        self._message_handler = handler

    # ── Listen (server side) ─────────────────────────────────

    async def listen(self, host: str = "localhost", port: int = 8765) -> None:
        """
        Start WebSocket server. For each connection:
        1. Receive HELLO from connecting peer
        2. Verify HELLO
        3. Send own HELLO
        4. Register peer
        5. Listen for messages
        """
        self._server = await ws_serve(
            self._handle_accepted_connection,
            host, port,
        )
        logger.info(f"[{self.my_id}] Listening on ws://{host}:{port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_accepted_connection(self, websocket) -> None:
        """Handle an incoming WebSocket connection (server side)."""
        peer_id = None
        try:
            peer_id = await self._handshake_as_acceptor(websocket)
            if not peer_id:
                await websocket.close(code=1008, reason="handshake failed")
                return
            logger.info(f"[{self.my_id}] Handshake complete with {peer_id}")
            await self._receive_loop(websocket, peer_id)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{self.my_id}] Connection closed with {peer_id or 'unknown'}")
        finally:
            if peer_id:
                self.registry.remove(peer_id)

    # ── Connect (client side) ────────────────────────────────

    async def connect(self, uri: str) -> str | None:
        """
        Connect to a remote peer.
        1. Open WebSocket
        2. Send own HELLO
        3. Receive HELLO from remote
        4. Verify and register peer
        5. Start receive loop in background

        Returns the peer's principal_id on success, None on failure.
        """
        try:
            websocket = await ws_connect(uri)
        except Exception as e:
            logger.error(f"[{self.my_id}] Connection failed: {e}")
            return None

        peer_id = await self._handshake_as_initiator(websocket)
        if peer_id is None:
            await websocket.close()
            return None

        logger.info(f"[{self.my_id}] Connected and handshake complete with {peer_id}")

        # Start receive loop in background
        asyncio.create_task(self._receive_loop_with_cleanup(websocket, peer_id))
        return peer_id

    async def _receive_loop_with_cleanup(self, websocket, peer_id: str) -> None:
        """Receive loop with cleanup on disconnect."""
        try:
            await self._receive_loop(websocket, peer_id)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{self.my_id}] Connection closed with {peer_id}")
        finally:
            self.registry.remove(peer_id)

    # ── Handshake ────────────────────────────────────────────

    async def _handshake_as_initiator(self, websocket) -> str | None:
        """Client-side handshake: send HELLO first, then receive."""
        # Send our HELLO
        hello = sign_hello(self.my_id, self.keypair)
        await websocket.send(json.dumps(hello.to_dict()))

        # Receive their HELLO
        raw = await websocket.recv()
        return self._process_hello(raw, websocket)

    async def _handshake_as_acceptor(self, websocket) -> str | None:
        """Server-side handshake: receive HELLO first, then send."""
        # Receive their HELLO
        raw = await websocket.recv()
        peer_id = self._process_hello(raw, websocket)

        if peer_id is None:
            return None

        # Send our HELLO
        hello = sign_hello(self.my_id, self.keypair)
        await websocket.send(json.dumps(hello.to_dict()))

        return peer_id

    def _process_hello(self, raw: str, websocket) -> str | None:
        """Parse, verify, and register a HELLO message. Returns peer_id or None."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.my_id}] Invalid HELLO message: {e}")
            return None

        if data.get("type") != "hello":
            logger.warning(f"[{self.my_id}] Expected HELLO, got type={data.get('type')!r}")
            return None

        try:
            hello = HelloMessage.from_dict(data)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"[{self.my_id}] Invalid HELLO message: {e}")
            return None

        if not verify_hello(hello):
            logger.warning(f"[{self.my_id}] HELLO verification failed from {hello.sender_id}")
            return None

        # Decode pubkey and register
        try:
            pubkey = b64_to_pubkey(hello.sender_pubkey)
        except Exception as e:
            logger.warning(f"[{self.my_id}] Invalid pubkey in HELLO: {e}")
            return None

        if not self.registry.register(hello.sender_id, pubkey, websocket):
            logger.warning(
                f"[{self.my_id}] Rejected HELLO from {hello.sender_id}: "
                f"pubkey differs from established session"
            )
            return None
        return hello.sender_id

    # ── Send ─────────────────────────────────────────────────

    async def send(self, recipient_id: str, payload: dict) -> bool:
        """
        Send a signed message to a registered peer.

        Returns True if sent, False if peer unknown or send failed.
        """
        connection = self.registry.get_connection(recipient_id)
        if connection is None:
            logger.warning(f"[{self.my_id}] Cannot send to unknown peer {recipient_id}")
            return False

        envelope = sign_envelope(
            payload, self.my_id,
            self.keypair, recipient_id,
        )

        try:
            await connection.send(json.dumps(envelope.to_dict()))
            return True
        except Exception as e:
            logger.error(f"[{self.my_id}] Send failed to {recipient_id}: {e}")
            return False

    # ── Receive ──────────────────────────────────────────────

    async def _receive_loop(self, websocket, peer_id: str) -> None:
        """Listen for messages from a connected peer."""
        async for raw in websocket:
            try:
                self._handle_incoming(raw, peer_id)
            except Exception as e:
                logger.error(f"[{self.my_id}] Error handling message from {peer_id}: {e}")

    def _handle_incoming(self, raw_message: str, expected_sender_id: str) -> None:
        """
        Parse, verify, and dispatch an incoming message.

        Rejects:
        - Invalid JSON
        - Invalid envelope structure
        - Payload hash mismatch (tampered payload)
        - Signature verification failure
        - sender_id not matching session-bound peer
        """
        try:
            data = json.loads(raw_message)
            envelope = MessageEnvelope.from_dict(data)
        except Exception as e:
            logger.warning(f"[{self.my_id}] Invalid envelope: {e}")
            return

        # Reject unknown envelope version
        if envelope.envelope_version != "1.0":
            logger.warning(
                f"[{self.my_id}] Unknown envelope version: {envelope.envelope_version!r}"
            )
            return

        # Reject sender_id mismatch (spoofing attempt)
        if envelope.sender_id != expected_sender_id:
            logger.warning(
                f"[{self.my_id}] Sender ID mismatch: "
                f"expected {expected_sender_id!r}, got {envelope.sender_id!r}"
            )
            return

        # Reject recipient_id mismatch (misrouted message)
        if envelope.recipient_id != self.my_id:
            logger.warning(
                f"[{self.my_id}] Recipient ID mismatch: "
                f"expected {self.my_id!r}, got {envelope.recipient_id!r}"
            )
            return

        # Look up the session-bound pubkey
        pubkey = self.registry.get_pubkey(envelope.sender_id)
        if pubkey is None:
            logger.warning(f"[{self.my_id}] Unknown sender: {envelope.sender_id}")
            return

        # Verify envelope (signature + payload hash)
        if not verify_envelope(envelope, pubkey):
            logger.warning(f"[{self.my_id}] Envelope verification failed from {envelope.sender_id}")
            return

        # Dispatch to handler
        if self._message_handler:
            try:
                payload = json.loads(envelope.payload)
            except json.JSONDecodeError:
                logger.warning(f"[{self.my_id}] Could not decode payload as JSON")
                return
            self._message_handler(envelope.sender_id, payload)
