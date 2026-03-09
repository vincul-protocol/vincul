"""
vincul.transport.keys — Identity persistence for VinculNet

Loads or creates Ed25519 keypairs at ~/.vincul/keys/{principal_id}.key
PEM format (PKCS8, no encryption).

Ensures stable identity across restarts.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from vincul.identity import KeyPair

logger = logging.getLogger("vincul.transport.keys")


DEFAULT_KEY_DIR = Path.home() / ".vincul" / "keys"


def _fingerprint(keypair: KeyPair) -> str:
    """SHA-256 fingerprint of the public key (for display)."""
    raw = keypair.public_key_bytes()
    return hashlib.sha256(raw).hexdigest()[:16]


def load_or_create_keypair(
    principal_id: str,
    key_dir: Path | None = None,
) -> KeyPair:
    """
    Load an existing keypair or generate a new one.

    Path: {key_dir}/{principal_id}.key (PEM, PKCS8, unencrypted)
    If generated, logs the fingerprint.
    """
    key_dir = key_dir or DEFAULT_KEY_DIR
    key_dir.mkdir(parents=True, exist_ok=True)

    key_path = key_dir / f"{principal_id}.key"

    if key_path.exists():
        pem_bytes = key_path.read_bytes()
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        private_key = load_pem_private_key(pem_bytes, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError(f"Key for {principal_id} is not Ed25519")
        keypair = KeyPair(
            principal_id=principal_id,
            private_key=private_key,
            public_key=private_key.public_key(),
        )
        return keypair

    # Generate new keypair
    keypair = KeyPair.generate(principal_id)

    # Save PEM
    pem_bytes = keypair.private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)
    # Restrict permissions (owner read/write only)
    os.chmod(key_path, 0o600)

    fingerprint = _fingerprint(keypair)
    logger.info(f"Generated new keypair for {principal_id}")
    logger.info(f"Fingerprint: {fingerprint}")
    logger.info(f"Saved to: {key_path}")

    return keypair
