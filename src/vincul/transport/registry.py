"""
vincul.transport.registry — In-memory peer registry for VinculNet

Maps principal_id → (pubkey, connection) for authenticated peers.
Standalone — no dependency on vincul.identity.PrincipalRegistry.

Populated during handshake, consulted during message send/verify.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


@dataclass
class PeerInfo:
    """Stored info about an authenticated peer."""
    principal_id: str
    pubkey: Ed25519PublicKey
    connection: Any  # WebSocket connection (or None in tests)


class PeerRegistry:
    """
    In-memory registry of authenticated VinculNet peers.

    After a successful HELLO handshake, the peer is registered here.
    Used to look up pubkeys for envelope verification and connections
    for message sending.
    """

    def __init__(self) -> None:
        self._peers: dict[str, PeerInfo] = {}

    def register(
        self,
        principal_id: str,
        pubkey: Ed25519PublicKey,
        connection: Any = None,
    ) -> bool:
        """
        Register an authenticated peer.

        If the peer is already registered with a different pubkey, rejects
        the registration (returns False). Same pubkey with a new connection
        is allowed (reconnection).

        Returns True on success, False if pubkey conflict.
        """
        existing = self._peers.get(principal_id)
        if existing is not None:
            # Compare raw pubkey bytes
            existing_bytes = existing.pubkey.public_bytes(Encoding.Raw, PublicFormat.Raw)
            new_bytes = pubkey.public_bytes(Encoding.Raw, PublicFormat.Raw)
            if existing_bytes != new_bytes:
                return False
            # Same pubkey, update connection only
            existing.connection = connection
            return True

        self._peers[principal_id] = PeerInfo(
            principal_id=principal_id,
            pubkey=pubkey,
            connection=connection,
        )
        return True

    def get_pubkey(self, principal_id: str) -> Ed25519PublicKey | None:
        """Look up a peer's public key. Returns None if unknown."""
        info = self._peers.get(principal_id)
        return info.pubkey if info else None

    def get_connection(self, principal_id: str) -> Any | None:
        """Look up a peer's WebSocket connection. Returns None if unknown."""
        info = self._peers.get(principal_id)
        return info.connection if info else None

    def is_known(self, principal_id: str) -> bool:
        """True if this principal_id has been registered."""
        return principal_id in self._peers

    def remove(self, principal_id: str) -> bool:
        """Remove a peer. Returns True if peer existed, False otherwise."""
        if principal_id in self._peers:
            del self._peers[principal_id]
            return True
        return False

    def all_peers(self) -> list[str]:
        """Return all registered principal_ids."""
        return list(self._peers.keys())
