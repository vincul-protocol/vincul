"""
vincul.transport.handshake — Authenticated HELLO handshake for VinculNet

Implements the HelloMessage dataclass and sign/verify functions.
Used during peer connection to establish mutual identity binding.

Domain tag: VINCULNET_HELLO_V1\x00

Handshake flow (TOFU — trust-on-first-use for MVP):
  Peer A → Peer B: HELLO (sender_id, sender_pubkey, timestamp, signature)
  Peer B → Peer A: HELLO (sender_id, sender_pubkey, timestamp, signature)
  Both sides verify and store: principal_id → pubkey
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vincul.hashing import jcs_serialize
from vincul.identity import KeyPair, verify


# ── Domain tag ───────────────────────────────────────────────

HELLO_DOMAIN_TAG = b"VINCULNET_HELLO_V1\x00"


# ── HelloMessage ─────────────────────────────────────────────

@dataclass(frozen=True)
class HelloMessage:
    """
    Handshake message exchanged when two VinculNet peers connect.

    sender_pubkey is included here (and ONLY here) — after handshake,
    pubkey binding is established and envelopes do not carry pubkeys.
    """
    sender_id: str
    sender_pubkey: str    # base64url-encoded Ed25519 public key
    timestamp: str        # ISO 8601 UTC
    signature: str        # base64url-encoded Ed25519 signature

    def to_dict(self) -> dict:
        """Serialize for wire transport."""
        return {
            "type": "hello",
            "sender_id": self.sender_id,
            "sender_pubkey": self.sender_pubkey,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HelloMessage":
        """Deserialize from wire transport."""
        return cls(
            sender_id=d["sender_id"],
            sender_pubkey=d["sender_pubkey"],
            timestamp=d["timestamp"],
            signature=d["signature"],
        )


def _build_sign_dict(sender_id: str, sender_pubkey: str, timestamp: str) -> dict:
    """Build the dict of fields that get signed."""
    return {
        "sender_id": sender_id,
        "sender_pubkey": sender_pubkey,
        "timestamp": timestamp,
    }


def _sign_bytes(sign_dict: dict) -> bytes:
    """Canonicalize and prepend domain tag — the bytes that get signed."""
    return HELLO_DOMAIN_TAG + jcs_serialize(sign_dict)


def pubkey_to_b64(public_key: Ed25519PublicKey) -> str:
    """Encode an Ed25519 public key as base64url string."""
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).decode("ascii")


def b64_to_pubkey(b64: str) -> Ed25519PublicKey:
    """Decode a base64url string to an Ed25519 public key."""
    raw = base64.urlsafe_b64decode(b64)
    return Ed25519PublicKey.from_public_bytes(raw)


# ── Public API ───────────────────────────────────────────────

def sign_hello(
    sender_id: str,
    keypair: KeyPair,
) -> HelloMessage:
    """
    Create a signed HelloMessage for handshake.

    1. Get public key from keypair
    2. Build sign_dict with sender_id, sender_pubkey, timestamp
    3. Sign: domain_tag + jcs_serialize(sign_dict)
    """
    sender_pubkey = keypair.public_key_b64()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sign_dict = _build_sign_dict(sender_id, sender_pubkey, timestamp)
    message_bytes = _sign_bytes(sign_dict)
    signature = keypair.sign_b64(message_bytes)

    return HelloMessage(
        sender_id=sender_id,
        sender_pubkey=sender_pubkey,
        timestamp=timestamp,
        signature=signature,
    )


def verify_hello(hello: HelloMessage) -> bool:
    """
    Verify a HelloMessage signature.

    The public key is taken from the message itself (TOFU model).
    Returns True if signature is valid, False otherwise.
    """
    try:
        pubkey = b64_to_pubkey(hello.sender_pubkey)
    except Exception:
        return False

    sign_dict = _build_sign_dict(hello.sender_id, hello.sender_pubkey, hello.timestamp)
    message_bytes = _sign_bytes(sign_dict)
    return verify(pubkey, message_bytes, hello.signature)
