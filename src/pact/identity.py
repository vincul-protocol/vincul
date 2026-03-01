"""
pact.identity — Principal identity, Ed25519 signing and verification
spec: spec/crypto/HASHING.md §5 (detached signature model)

Wraps PyCA cryptography for Ed25519 only.
Signing is the only module in pact that imports an external library.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.exceptions import InvalidSignature


# ── Types ─────────────────────────────────────────────────────

PrincipalId = str   # e.g. "principal:alice", "agent:raanan"
AgentId = str


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 keypair bound to a principal_id."""
    principal_id: PrincipalId
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @classmethod
    def generate(cls, principal_id: PrincipalId) -> "KeyPair":
        """Generate a fresh Ed25519 keypair for a principal."""
        private_key = Ed25519PrivateKey.generate()
        return cls(
            principal_id=principal_id,
            private_key=private_key,
            public_key=private_key.public_key(),
        )

    def public_key_bytes(self) -> bytes:
        """Raw 32-byte Ed25519 public key."""
        return self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    def public_key_b64(self) -> str:
        """Base64url-encoded public key (for wire format / storage)."""
        return base64.urlsafe_b64encode(self.public_key_bytes()).decode("ascii")

    def sign(self, message: bytes) -> bytes:
        """Sign a message. Returns raw 64-byte signature."""
        return self.private_key.sign(message)

    def sign_b64(self, message: bytes) -> str:
        """Sign and return base64url-encoded signature."""
        return base64.urlsafe_b64encode(self.sign(message)).decode("ascii")


@dataclass
class PrincipalRegistry:
    """
    In-memory registry mapping principal_id → public key.
    In production this would be backed by persistent storage or a DID resolver.
    For demo and tests: populated directly.
    """
    _registry: dict[PrincipalId, Ed25519PublicKey] = field(default_factory=dict)

    def register(self, principal_id: PrincipalId, public_key: Ed25519PublicKey) -> None:
        self._registry[principal_id] = public_key

    def register_keypair(self, keypair: KeyPair) -> None:
        self._registry[keypair.principal_id] = keypair.public_key

    def resolve(self, principal_id: PrincipalId) -> Ed25519PublicKey | None:
        """Resolve a principal_id to its public key. Returns None if unknown."""
        return self._registry.get(principal_id)

    def known(self, principal_id: PrincipalId) -> bool:
        return principal_id in self._registry


# ── Signing and verification ──────────────────────────────────

def sign(keypair: KeyPair, message: bytes) -> str:
    """
    Sign a message with an Ed25519 keypair.
    Returns base64url-encoded signature string (for receipt signatures field).
    """
    return keypair.sign_b64(message)


def verify(
    public_key: Ed25519PublicKey,
    message: bytes,
    signature_b64: str,
) -> bool:
    """
    Verify an Ed25519 signature.
    signature_b64: base64url-encoded 64-byte signature.
    Returns True if valid, False if invalid.
    """
    try:
        sig_bytes = base64.urlsafe_b64decode(signature_b64)
        public_key.verify(sig_bytes, message)
        return True
    except (InvalidSignature, Exception):
        return False


def verify_by_id(
    registry: PrincipalRegistry,
    principal_id: PrincipalId,
    message: bytes,
    signature_b64: str,
) -> bool:
    """
    Resolve a principal and verify a signature.
    Returns False if principal is unknown (not an error — treated as unverifiable).
    """
    pubkey = registry.resolve(principal_id)
    if pubkey is None:
        return False
    return verify(pubkey, message, signature_b64)


# ── AttestationSignature wire format ──────────────────────────

@dataclass(frozen=True)
class AttestationSignature:
    """
    Per ATTEST.md §3.2. Included in receipt.signatures block.
    signature_over is the exact signature message (for auditability).
    """
    signer_id: PrincipalId
    algo: str                  # "Ed25519" — only valid value in v0.2
    signature_over: str        # the signature message string (UTF-8)
    signature_bytes: str       # base64url-encoded signature

    def to_dict(self) -> dict:
        return {
            "signer_id": self.signer_id,
            "algo": self.algo,
            "signature_over": self.signature_over,
            "signature_bytes": self.signature_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AttestationSignature":
        return cls(
            signer_id=d["signer_id"],
            algo=d["algo"],
            signature_over=d["signature_over"],
            signature_bytes=d["signature_bytes"],
        )
