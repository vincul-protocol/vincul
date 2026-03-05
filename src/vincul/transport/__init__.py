"""
vincul.transport — VinculNet authenticated peer transport layer

Stage 1: signed WebSocket communication between peers.
Builds on vincul.identity (Ed25519) and vincul.hashing (JCS + SHA-256).
"""

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
    pubkey_to_b64,
)
from vincul.transport.registry import PeerRegistry
from vincul.transport.keys import load_or_create_keypair
from vincul.transport.peer import VinculPeer
from vincul.transport.protocol_peer import ProtocolPeer

__all__ = [
    "MessageEnvelope",
    "sign_envelope",
    "verify_envelope",
    "HelloMessage",
    "sign_hello",
    "verify_hello",
    "b64_to_pubkey",
    "pubkey_to_b64",
    "PeerRegistry",
    "VinculPeer",
    "load_or_create_keypair",
    "ProtocolPeer",
]
