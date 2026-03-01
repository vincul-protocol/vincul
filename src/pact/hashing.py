"""
pact.hashing — Canonical serialization and domain-prefixed hashing
spec: spec/crypto/HASHING.md

Implements:
- JCS (JSON Canonicalization Scheme, RFC 8785)
- Domain-prefixed SHA-256 hashing
- Set-like array normalization

Zero external dependencies. Pure stdlib.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


# ── Domain separation tags (HASHING.md §4) ───────────────────

DOMAIN_PREFIXES: dict[str, str] = {
    "scope":      "PACT_SCOPE_V1\x00",
    "receipt":    "PACT_RECEIPT_V1\x00",
    "contract":   "PACT_CONTRACT_V1\x00",
    "constraint": "PACT_CONSTRAINT_V1\x00",
    "profile":    "PACT_PROFILE_V1\x00",
}

ATTEST_DOMAIN_TAG = "PACT_ATTEST_V1\x00"


# ── JCS (RFC 8785) ────────────────────────────────────────────

def jcs_serialize(obj: Any) -> bytes:
    """
    Serialize to JCS canonical JSON (RFC 8785).
    Returns UTF-8 encoded bytes with no trailing newline.
    """
    return _serialize(obj).encode("utf-8")


def _serialize(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _serialize_float(obj)
    if isinstance(obj, str):
        return _serialize_string(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_serialize(v) for v in obj) + "]"
    if isinstance(obj, dict):
        pairs = ",".join(
            _serialize_string(k) + ":" + _serialize(obj[k])
            for k in sorted(obj.keys())
        )
        return "{" + pairs + "}"
    raise TypeError(f"JCS: unsupported type {type(obj).__name__!r}")


def _serialize_float(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise ValueError("JCS: NaN and Infinity are not permitted")
    return "0" if f == 0.0 else repr(f)


def _serialize_string(s: str) -> str:
    out = ['"']
    for ch in s:
        code = ord(ch)
        if   ch == '"':    out.append('\\"')
        elif ch == '\\':   out.append('\\\\')
        elif ch == '\b':   out.append('\\b')
        elif ch == '\f':   out.append('\\f')
        elif ch == '\n':   out.append('\\n')
        elif ch == '\r':   out.append('\\r')
        elif ch == '\t':   out.append('\\t')
        elif code < 0x20:  out.append(f'\\u{code:04x}')
        else:              out.append(ch)
    out.append('"')
    return "".join(out)


# ── Core hash functions ───────────────────────────────────────

def pact_hash(object_type: str, payload: dict) -> str:
    """
    Compute a domain-separated SHA-256 hash over a JCS-serialized payload.

    object_type: one of "scope", "receipt", "contract", "profile"
    payload: dict with receipt_hash / descriptor_hash and signatures excluded
    Returns: lowercase hex string (64 chars)
    """
    if object_type not in DOMAIN_PREFIXES:
        raise ValueError(
            f"Unknown object type {object_type!r}. "
            f"Valid: {sorted(DOMAIN_PREFIXES)}"
        )
    prefix = DOMAIN_PREFIXES[object_type].encode("utf-8")
    return hashlib.sha256(prefix + jcs_serialize(payload)).hexdigest()


def pact_hash_constraint(expression: str) -> str:
    """
    Hash a ConstraintExpression string (not JSON-encoded).
    The expression is the raw DSL string, e.g. "TOP" or "action.params.x <= 60".
    """
    prefix = DOMAIN_PREFIXES["constraint"].encode("utf-8")
    return hashlib.sha256(prefix + expression.encode("utf-8")).hexdigest()


def attestation_signature_message(
    attests_receipt_hash: str,
    response_hash_value: str,
) -> bytes:
    """
    Construct the attestation signature message per ATTEST.md §3.1:
      "PACT_ATTEST_V1\\x00" || attests_receipt_hash || response_hash.value

    Both hash arguments are lowercase hex strings.
    Returns raw bytes ready for signing with Ed25519.
    """
    tag = ATTEST_DOMAIN_TAG.encode("utf-8")
    return tag + attests_receipt_hash.encode("utf-8") + response_hash_value.encode("utf-8")


def response_hash_sha256(canonical_response_bytes: bytes) -> str:
    """SHA-256 hash of an external response payload, for use in attestation receipts."""
    return hashlib.sha256(canonical_response_bytes).hexdigest()


# ── Set-like array normalization (HASHING.md §7.5) ───────────
# All functions deep-copy their input — never mutate in place.

def normalize_contract(contract: dict) -> dict:
    """Sort principals by principal_id (Unicode code point order)."""
    obj = json.loads(json.dumps(contract))
    if principals := obj.get("principals"):
        obj["principals"] = sorted(principals, key=lambda p: p["principal_id"])
    return obj


def normalize_profile(profile: dict) -> dict:
    """Sort all set-like string arrays in a Compliance Profile."""
    obj = json.loads(json.dumps(profile))
    for field in (
        "supported_receipt_kinds",
        "supported_failure_codes",
        "signature_algorithms",
    ):
        if obj.get(field) is not None:
            obj[field] = sorted(obj[field])
    if obj.get("attestation_schemas") is not None:
        obj["attestation_schemas"] = sorted(obj["attestation_schemas"])
    return obj


def normalize_ledger_balances(balances: list[dict]) -> list[dict]:
    """Sort ledger snapshot balances by dimension (Unicode code point order)."""
    return sorted(
        json.loads(json.dumps(balances)),
        key=lambda b: b["dimension"]
    )


# ── Validation helpers ────────────────────────────────────────

def is_valid_pact_hash(value: str) -> bool:
    """Return True if value is a well-formed lowercase 64-char hex hash."""
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
        return value == value.lower()
    except ValueError:
        return False
