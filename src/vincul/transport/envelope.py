"""
vincul.transport.envelope — Signed message envelopes for VinculNet

Implements the MessageEnvelope dataclass and sign/verify functions.
Uses vincul.hashing for canonicalization and vincul.identity for Ed25519.

Domain tag: VINCULNET_ENVELOPE_V1\x00

Security rules:
  - Never sign raw string concatenations
  - Always construct a dict of fields to sign
  - Canonicalize deterministically via JCS (RFC 8785)
  - Prefix bytes with domain separation tag before signing
  - Reject if signature fails, payload_hash mismatches, or sender_id spoofed
"""

from __future__ import annotations

import base64
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from vincul.hashing import domain_hash, jcs_serialize
from vincul.identity import KeyPair, verify


# ── Domain tags ──────────────────────────────────────────────

ENVELOPE_DOMAIN_TAG = b"VINCULNET_ENVELOPE_V1\x00"

ENVELOPE_VERSION = "1.0"


# ── MessageEnvelope ──────────────────────────────────────────

@dataclass(frozen=True)
class MessageEnvelope:
    """
    A signed message envelope for VinculNet transport.

    The signature covers the sign_dict (metadata), not the raw payload.
    The payload is integrity-protected via payload_hash.
    sender_pubkey is NOT included — pubkey binding happens during handshake.
    """
    envelope_version: str
    sender_id: str
    recipient_id: str
    payload: bytes
    payload_hash: str
    timestamp: str
    message_id: str
    signature: str

    def to_dict(self) -> dict:
        """Serialize for wire transport (JSON-safe)."""
        return {
            "envelope_version": self.envelope_version,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "payload": base64.urlsafe_b64encode(self.payload).decode("ascii"),
            "payload_hash": self.payload_hash,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MessageEnvelope":
        """Deserialize from wire transport."""
        return cls(
            envelope_version=d["envelope_version"],
            sender_id=d["sender_id"],
            recipient_id=d["recipient_id"],
            payload=base64.urlsafe_b64decode(d["payload"]),
            payload_hash=d["payload_hash"],
            timestamp=d["timestamp"],
            message_id=d["message_id"],
            signature=d["signature"],
        )


def _build_sign_dict(
    envelope_version: str,
    sender_id: str,
    recipient_id: str,
    payload_hash: str,
    timestamp: str,
    message_id: str,
) -> dict:
    """Build the dict of fields that get signed."""
    return {
        "envelope_version": envelope_version,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "payload_hash": payload_hash,
        "timestamp": timestamp,
        "message_id": message_id,
    }


def _sign_bytes(sign_dict: dict) -> bytes:
    """Canonicalize and prepend domain tag — the bytes that get signed."""
    return ENVELOPE_DOMAIN_TAG + jcs_serialize(sign_dict)


# ── Public API ───────────────────────────────────────────────

def sign_envelope(
    payload: dict,
    sender_id: str,
    keypair: KeyPair,
    recipient_id: str,
) -> MessageEnvelope:
    """
    Create a signed MessageEnvelope.

    1. Serialize payload to canonical JSON via jcs_serialize
    2. Compute domain-prefixed payload_hash
    3. Build sign_dict with envelope metadata
    4. Sign: domain_tag + jcs_serialize(sign_dict)
    5. Base64-encode signature
    """
    # Serialize payload
    payload_bytes = jcs_serialize(payload)

    # Hash payload with domain tag
    payload_hash = domain_hash(ENVELOPE_DOMAIN_TAG, payload_bytes)

    # Generate metadata
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message_id = str(uuid_mod.uuid4())

    # Build sign_dict and sign
    sign_dict = _build_sign_dict(
        ENVELOPE_VERSION, sender_id, recipient_id,
        payload_hash, timestamp, message_id,
    )
    message_bytes = _sign_bytes(sign_dict)
    signature = keypair.sign_b64(message_bytes)

    return MessageEnvelope(
        envelope_version=ENVELOPE_VERSION,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload_bytes,
        payload_hash=payload_hash,
        timestamp=timestamp,
        message_id=message_id,
        signature=signature,
    )


def verify_envelope(
    envelope: MessageEnvelope,
    expected_pubkey: Ed25519PublicKey,
) -> bool:
    """
    Verify a MessageEnvelope.

    Checks:
    1. Recompute payload_hash and compare
    2. Reconstruct sign_dict and verify signature

    Returns True if both checks pass, False otherwise.
    """
    # Check payload integrity
    recomputed_hash = domain_hash(ENVELOPE_DOMAIN_TAG, envelope.payload)
    if recomputed_hash != envelope.payload_hash:
        return False

    # Reconstruct sign_dict and verify signature
    sign_dict = _build_sign_dict(
        envelope.envelope_version, envelope.sender_id, envelope.recipient_id,
        envelope.payload_hash, envelope.timestamp, envelope.message_id,
    )
    message_bytes = _sign_bytes(sign_dict)
    return verify(expected_pubkey, message_bytes, envelope.signature)
