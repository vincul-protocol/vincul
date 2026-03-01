#!/usr/bin/env python3
"""
Pact Protocol — Test Vector Generator v0.2
tools/test-vectors/generate.py

Implements:
- JCS (JSON Canonicalization Scheme, RFC 8785) serialization
- Set-like array normalization (sorted lexicographically before hashing)
- Domain-prefixed SHA-256 hashing per spec/crypto/HASHING.md
- Test vectors for all v0.2 object types and receipt kinds

Usage:
  python3 generate.py
"""

import hashlib
import json
import math


# ─────────────────────────────────────────────────────────────
# JCS (RFC 8785) Implementation
# ─────────────────────────────────────────────────────────────

def jcs_serialize(obj) -> bytes:
    return _serialize(obj).encode("utf-8")


def _serialize(obj) -> str:
    if obj is None:
        return "null"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif isinstance(obj, int):
        return str(obj)
    elif isinstance(obj, float):
        return _serialize_float(obj)
    elif isinstance(obj, str):
        return _serialize_string(obj)
    elif isinstance(obj, list):
        return "[" + ",".join(_serialize(v) for v in obj) + "]"
    elif isinstance(obj, dict):
        sorted_keys = sorted(obj.keys())
        pairs = ",".join(
            _serialize_string(k) + ":" + _serialize(obj[k])
            for k in sorted_keys
        )
        return "{" + pairs + "}"
    else:
        raise TypeError(f"Unsupported type: {type(obj)}")


def _serialize_float(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise ValueError(f"JCS does not support NaN or Infinity: {f}")
    if f == 0.0:
        return "0"
    return repr(f)


def _serialize_string(s: str) -> str:
    out = ['"']
    for ch in s:
        code = ord(ch)
        if ch == '"':   out.append('\\"')
        elif ch == '\\': out.append('\\\\')
        elif ch == '\b': out.append('\\b')
        elif ch == '\f': out.append('\\f')
        elif ch == '\n': out.append('\\n')
        elif ch == '\r': out.append('\\r')
        elif ch == '\t': out.append('\\t')
        elif code < 0x20: out.append(f'\\u{code:04x}')
        else: out.append(ch)
    out.append('"')
    return "".join(out)


# ─────────────────────────────────────────────────────────────
# Set-like array normalization
# Arrays that are logically sets must be sorted before hashing.
# Fields requiring this treatment per the spec:
#   - Coalition Contract: principals (by principal_id)
#   - Compliance Profile: supported_receipt_kinds, supported_failure_codes,
#                         signature_algorithms, attestation_schemas
#   - Ledger Snapshot: balances (by dimension)
# ─────────────────────────────────────────────────────────────

def normalize_contract(obj: dict) -> dict:
    """Sort principals by principal_id before hashing."""
    obj = json.loads(json.dumps(obj))  # deep copy
    if "principals" in obj:
        obj["principals"] = sorted(obj["principals"], key=lambda p: p["principal_id"])
    return obj


def normalize_profile(obj: dict) -> dict:
    """Sort all set-like arrays in a Compliance Profile."""
    obj = json.loads(json.dumps(obj))
    for field in ["supported_receipt_kinds", "supported_failure_codes",
                  "signature_algorithms", "attestation_schemas"]:
        if field in obj and obj[field] is not None:
            obj[field] = sorted(obj[field])
    return obj


def normalize_ledger_snapshot_detail(detail: dict) -> dict:
    """Sort balances by dimension."""
    detail = json.loads(json.dumps(detail))
    if "balances" in detail:
        detail["balances"] = sorted(detail["balances"], key=lambda b: b["dimension"])
    return detail


# ─────────────────────────────────────────────────────────────
# Pact Hashing
# ─────────────────────────────────────────────────────────────

DOMAIN_PREFIXES = {
    "scope":      "PACT_SCOPE_V1\x00",
    "receipt":    "PACT_RECEIPT_V1\x00",
    "contract":   "PACT_CONTRACT_V1\x00",
    "constraint": "PACT_CONSTRAINT_V1\x00",
    "profile":    "PACT_PROFILE_V1\x00",
}


def pact_hash(object_type: str, payload: dict) -> str:
    prefix = DOMAIN_PREFIXES[object_type].encode("utf-8")
    canonical = jcs_serialize(payload)
    return hashlib.sha256(prefix + canonical).hexdigest()


def pact_hash_constraint(expression: str) -> str:
    prefix = DOMAIN_PREFIXES["constraint"].encode("utf-8")
    return hashlib.sha256(prefix + expression.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# Shared fixture data (reused across vectors)
# ─────────────────────────────────────────────────────────────

SCOPE_VECTOR = {
    "id": "00000000-0000-0000-0000-000000000001",
    "issued_by_scope_id": None,
    "issued_by": "principal:test",
    "issued_at": "2025-01-01T00:00:00Z",
    "expires_at": None,
    "domain": {"namespace": "test.resource", "types": ["OBSERVE"]},
    "predicate": "TOP",
    "ceiling": "TOP",
    "delegate": False,
    "revoke": "principal_only",
    "status": "active",
    "effective_at": None
}

CONTRACT_VECTOR = {
    "contract_id": "00000000-0000-0000-0000-000000000003",
    "version": "0.1",
    "purpose": {
        "title": "Test Coalition",
        "description": "Minimal coalition for test vector generation",
        "expires_at": None
    },
    "principals": [
        {"principal_id": "principal:test", "role": "owner", "revoke_right": True},
        {"principal_id": "principal:peer", "role": "member", "revoke_right": False}
    ],
    "governance": {
        "decision_rule": "unanimous",
        "threshold": None,
        "signatory_policy": {
            "delegation":     {"required_signers": ["delegator"]},
            "commitment":     {"required_signers": ["initiator"]},
            "revocation":     {"required_signers": ["principal"]},
            "revert_attempt": {"required_signers": ["initiator"]},
            "failure":        {"required_signers": []},
            "dissolution":    {"required_signers": ["principal"]}
        }
    },
    "budget_policy": {
        "allowed": False,
        "dimensions": None,
        "per_principal_limit": None
    },
    "activation": {
        "status": "active",
        "activated_at": "2025-01-01T00:00:00Z",
        "dissolved_at": None
    }
}

PROFILE_VECTOR = {
    "profile_id": "pact-core-minimal-v0.2",
    "protocol_version": "0.2",
    "implementation": {
        "name": "pact-reference",
        "version": "0.2.0",
        "vendor": None
    },
    "bounds": {
        "max_delegation_depth": 4,
        "max_scope_chain_length": 8,
        "revocation_resolution_deadline_ms": 5000,
        "ledger_snapshot_interval_seconds": None,
        "max_receipt_chain_fanout": None,
        "max_constraint_atoms": 32,
        "max_constraint_nesting_depth": 4
    },
    "supported_receipt_kinds": [
        "commitment", "contract_dissolution", "delegation",
        "failure", "revert_attempt", "revocation"
    ],
    "supported_failure_codes": [
        "ANCESTOR_INVALID", "BUDGET_EXCEEDED", "CEILING_VIOLATED",
        "CONTRACT_DISSOLVED", "CONTRACT_EXPIRED", "CONTRACT_NOT_ACTIVE",
        "DELEGATION_MALFORMED", "DELEGATION_UNAUTHORIZED",
        "REVOCATION_STATE_UNRESOLVED", "REVOCATION_UNAUTHORIZED",
        "SCOPE_EXCEEDED", "SCOPE_EXPIRED", "SCOPE_REVOKED",
        "TYPE_ESCALATION", "UNKNOWN"
    ],
    "signature_algorithms": ["Ed25519"],
    "attestation_schemas": None
}


def make_receipt_base(receipt_id, kind, issued_at, action, description,
                      initiated_by, scope_id, scope_hash, contract_id,
                      contract_hash, signatories, outcome, detail,
                      prior_receipt=None):
    return {
        "receipt_id": receipt_id,
        "receipt_kind": kind,
        "issued_at": issued_at,
        "intent": {
            "action": action,
            "description": description,
            "initiated_by": initiated_by
        },
        "authority": {
            "scope_id": scope_id,
            "scope_hash": scope_hash,
            "contract_id": contract_id,
            "contract_hash": contract_hash,
            "signatories": signatories
        },
        "result": {
            "outcome": outcome,
            "detail": detail
        },
        "prior_receipt": prior_receipt
    }


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 68)
    print("Pact Protocol — Test Vectors v0.2")
    print("spec/crypto/HASHING.md §7")
    print("=" * 68)

    results = {}

    # ── 1. Scope ──────────────────────────────────────────────
    scope_hash = pact_hash("scope", SCOPE_VECTOR)
    results["scope_hash"] = scope_hash
    scope_canonical = jcs_serialize(SCOPE_VECTOR).decode("utf-8")
    print(f"\n── Scope ────────────────────────────────────────────────────")
    print(f"JCS: {scope_canonical}")
    print(f"Hash: {scope_hash}")

    # ── 2. Contract (with normalized principals) ──────────────
    contract_normalized = normalize_contract(CONTRACT_VECTOR)
    contract_hash = pact_hash("contract", contract_normalized)
    results["contract_hash"] = contract_hash
    print(f"\n── Contract ─────────────────────────────────────────────────")
    print(f"Hash: {contract_hash}")

    # ── 3. Constraints ────────────────────────────────────────
    constraint_top_hash = pact_hash_constraint("TOP")
    constraint_atom_hash = pact_hash_constraint("action.params.duration_minutes <= 60")
    results["constraint_TOP"] = constraint_top_hash
    results["constraint_atom"] = constraint_atom_hash
    print(f"\n── Constraints ──────────────────────────────────────────────")
    print(f"TOP:  {constraint_top_hash}")
    print(f"atom: {constraint_atom_hash}")

    # ── 4. Compliance Profile (with sorted arrays) ────────────
    profile_normalized = normalize_profile(PROFILE_VECTOR)
    profile_hash = pact_hash("profile", profile_normalized)
    results["profile_hash"] = profile_hash
    print(f"\n── Compliance Profile ───────────────────────────────────────")
    print(f"Hash: {profile_hash}")

    # ── 5. Delegation Receipt (v0.1) ──────────────────────────
    delegation_detail = {
        "child_scope_id": "00000000-0000-0000-0000-000000000004",
        "child_scope_hash": scope_hash,
        "parent_scope_id": "00000000-0000-0000-0000-000000000001",
        "types_granted": ["OBSERVE"],
        "delegate_granted": False,
        "revoke_granted": "principal_only",
        "expires_at": None,
        "ceiling_hash": constraint_top_hash
    }
    delegation_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000002",
        kind="delegation",
        issued_at="2025-01-01T00:01:00Z",
        action="delegate",
        description="Delegate OBSERVE on test.resource to agent:child",
        initiated_by="principal:test",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:test"],
        outcome="success",
        detail=delegation_detail
    )
    delegation_hash = pact_hash("receipt", delegation_receipt)
    results["receipt_delegation"] = delegation_hash
    print(f"\n── Receipt: delegation ──────────────────────────────────────")
    print(f"Hash: {delegation_hash}")

    # ── 6. Commitment Receipt ─────────────────────────────────
    commitment_detail = {
        "action_type": "COMMIT",
        "namespace": "test.resource",
        "resource": "event:00000001",
        "params": {"duration_minutes": 60},
        "reversible": True,
        "revert_window": "PT10M",
        "external_ref": "ext:booking:abc123",
        "budget_consumed": None
    }
    commitment_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000005",
        kind="commitment",
        issued_at="2025-01-01T00:02:00Z",
        action="commit",
        description="Create event:00000001 on test.resource",
        initiated_by="principal:test",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:test"],
        outcome="success",
        detail=commitment_detail
    )
    commitment_hash = pact_hash("receipt", commitment_receipt)
    results["receipt_commitment"] = commitment_hash
    print(f"\n── Receipt: commitment ──────────────────────────────────────")
    print(f"Hash: {commitment_hash}")

    # ── 7. Attestation Receipt ────────────────────────────────
    response_hash_value = hashlib.sha256(b'{"id":"booking:abc123","status":"confirmed"}').hexdigest()
    attestation_detail = {
        "attests_receipt_id": "00000000-0000-0000-0000-000000000005",
        "attests_receipt_hash": commitment_hash,
        "response_hash": {
            "algo": "sha256",
            "value": response_hash_value
        },
        "response_schema": "test.booking.v1",
        "external_ref": "ext:booking:abc123",
        "produced_at": "2025-01-01T00:02:05Z"
    }
    attestation_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000006",
        kind="attestation",
        issued_at="2025-01-01T00:02:10Z",
        action="attest",
        description="Attest booking confirmation for commitment 00000000-0000-0000-0000-000000000005",
        initiated_by="principal:peer",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:peer"],
        outcome="success",
        detail=attestation_detail,
        prior_receipt=commitment_hash
    )
    attestation_hash = pact_hash("receipt", attestation_receipt)
    results["receipt_attestation"] = attestation_hash
    # Attestation signature message (not the receipt hash)
    sig_message = f"PACT_ATTEST_V1\x00{commitment_hash}{response_hash_value}"
    results["attestation_sig_message"] = hashlib.sha256(sig_message.encode()).hexdigest()
    print(f"\n── Receipt: attestation ─────────────────────────────────────")
    print(f"Hash:            {attestation_hash}")
    print(f"response_hash:   {response_hash_value}")
    print(f"sig_msg SHA-256: {results['attestation_sig_message']} (fingerprint of signature message)")

    # ── 8. Ledger Snapshot Receipt ────────────────────────────
    ledger_detail_raw = {
        "snapshot_type": "revocation",
        "covers_scope_id": "00000000-0000-0000-0000-000000000001",
        "snapshot_period": {
            "from": "2025-01-01T00:00:00Z",
            "to": "2025-01-01T01:00:00Z"
        },
        "balances": [
            {
                "dimension": "GBP",
                "ceiling": 100.00,
                "consumed": 9.99,
                "remaining": 90.01,
                "commitment_count": 1
            }
        ],
        "prior_snapshot": None,
        "commitment_refs": ["00000000-0000-0000-0000-000000000005"]
    }
    ledger_detail = normalize_ledger_snapshot_detail(ledger_detail_raw)
    ledger_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000007",
        kind="ledger_snapshot",
        issued_at="2025-01-01T01:00:00Z",
        action="ledger_snapshot",
        description="Revocation-time ledger snapshot for scope 00000000-0000-0000-0000-000000000001",
        initiated_by="principal:test",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:test"],
        outcome="success",
        detail=ledger_detail
    )
    ledger_hash = pact_hash("receipt", ledger_receipt)
    results["receipt_ledger_snapshot"] = ledger_hash
    print(f"\n── Receipt: ledger_snapshot ─────────────────────────────────")
    print(f"Hash: {ledger_hash}")

    # ── 9. Contract Dissolution Receipt ──────────────────────
    # Dissolved contract: status → dissolved, dissolved_at set
    dissolved_contract = json.loads(json.dumps(contract_normalized))
    dissolved_contract["activation"]["status"] = "dissolved"
    dissolved_contract["activation"]["dissolved_at"] = "2025-01-01T02:00:00Z"
    contract_hash_after = pact_hash("contract", dissolved_contract)
    results["contract_hash_after_dissolution"] = contract_hash_after

    dissolution_detail = {
        "contract_id": "00000000-0000-0000-0000-000000000003",
        "contract_hash_before": contract_hash,
        "contract_hash_after": contract_hash_after,
        "dissolved_at": "2025-01-01T02:00:00Z",
        "dissolved_by": "principal:test",
        "decision_rule": "unanimous",
        "signatures_present": 2,
        "ledger_snapshot_hash": None
    }
    dissolution_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000008",
        kind="contract_dissolution",
        issued_at="2025-01-01T02:00:00Z",
        action="dissolve_contract",
        description="Coalition dissolved by unanimous decision",
        initiated_by="principal:test",
        scope_id=None,
        scope_hash=None,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:peer", "principal:test"],
        outcome="success",
        detail=dissolution_detail
    )
    dissolution_hash = pact_hash("receipt", dissolution_receipt)
    results["receipt_contract_dissolution"] = dissolution_hash
    print(f"\n── Receipt: contract_dissolution ────────────────────────────")
    print(f"contract_hash_before: {contract_hash}")
    print(f"contract_hash_after:  {contract_hash_after}")
    print(f"Receipt hash:         {dissolution_hash}")

    # ── 10. Revocation and Failure Receipts ───────────────────
    revocation_detail = {
        "revocation_root": "00000000-0000-0000-0000-000000000001",
        "revoked_by": "principal:test",
        "authority_type": "principal",
        "effective_at": "2025-01-01T01:00:00Z",
        "cascade_method": "root+proof",
        "revert_attempts": [],
        "non_revertable": []
    }
    revocation_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000009",
        kind="revocation",
        issued_at="2025-01-01T01:00:00Z",
        action="revoke",
        description="Revoke scope 00000000-0000-0000-0000-000000000001",
        initiated_by="principal:test",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=["principal:test"],
        outcome="success",
        detail=revocation_detail
    )
    revocation_hash = pact_hash("receipt", revocation_receipt)
    results["receipt_revocation"] = revocation_hash
    print(f"\n── Receipt: revocation ──────────────────────────────────────")
    print(f"Hash: {revocation_hash}")

    failure_detail = {
        "error_code": "SCOPE_REVOKED",
        "message": "This scope was revoked by principal:test at 2025-01-01T01:00:00Z.",
        "recoverable": False,
        "scope_id": "00000000-0000-0000-0000-000000000001",
        "scope_hash": scope_hash,
        "contract_id": "00000000-0000-0000-0000-000000000003",
        "contract_hash": contract_hash,
        "revocation_root_scope_id": "00000000-0000-0000-0000-000000000001",
        "effective_at": "2025-01-01T01:00:00Z",
        "revocation_receipt_hash": revocation_hash
    }
    failure_receipt = make_receipt_base(
        receipt_id="00000000-0000-0000-0000-000000000010",
        kind="failure",
        issued_at="2025-01-01T01:05:00Z",
        action="fail",
        description="Action denied: scope has been revoked",
        initiated_by="principal:test",
        scope_id="00000000-0000-0000-0000-000000000001",
        scope_hash=scope_hash,
        contract_id="00000000-0000-0000-0000-000000000003",
        contract_hash=contract_hash,
        signatories=[],
        outcome="failure",
        detail=failure_detail,
        prior_receipt=revocation_hash
    )
    failure_hash = pact_hash("receipt", failure_receipt)
    results["receipt_failure_scope_revoked"] = failure_hash
    print(f"\n── Receipt: failure (SCOPE_REVOKED) ─────────────────────────")
    print(f"Hash: {failure_hash}")

    # ── Summary table ─────────────────────────────────────────
    print(f"\n{'=' * 68}")
    print("SUMMARY — paste into HASHING.md §7")
    print('=' * 68)
    labels = [
        ("scope_hash",                   "Scope descriptor"),
        ("contract_hash",                "Coalition Contract (active)"),
        ("contract_hash_after_dissolution", "Coalition Contract (dissolved)"),
        ("constraint_TOP",               "ConstraintExpression: TOP"),
        ("constraint_atom",              "ConstraintExpression: action.params.duration_minutes <= 60"),
        ("profile_hash",                 "Compliance Profile: pact-core-minimal-v0.2"),
        ("receipt_delegation",           "Receipt: delegation"),
        ("receipt_commitment",           "Receipt: commitment"),
        ("receipt_attestation",          "Receipt: attestation"),
        ("receipt_ledger_snapshot",      "Receipt: ledger_snapshot"),
        ("receipt_revocation",           "Receipt: revocation"),
        ("receipt_contract_dissolution", "Receipt: contract_dissolution"),
        ("receipt_failure_scope_revoked","Receipt: failure (SCOPE_REVOKED)"),
    ]
    for key, label in labels:
        print(f"  {label}")
        print(f"    {results[key]}")

    # ── Verification ──────────────────────────────────────────
    print(f"\n── JCS Verification ─────────────────────────────────────────")
    assert jcs_serialize({"z":1,"a":2,"m":3}) == b'{"a":2,"m":3,"z":1}', "FAIL: key ordering"
    print("  Key ordering: PASS")
    assert jcs_serialize({"b":{"z":1,"a":2},"a":True}) == b'{"a":true,"b":{"a":2,"z":1}}', "FAIL: nested"
    print("  Nested key ordering: PASS")
    assert jcs_serialize({"x":None,"y":False,"z":0}) == b'{"x":null,"y":false,"z":0}', "FAIL: null/false/zero"
    print("  Null/false/zero: PASS")

    print("\n── Array Normalization Verification ─────────────────────────")
    p = normalize_profile({"supported_receipt_kinds": ["failure", "delegation", "commitment"]})
    assert p["supported_receipt_kinds"] == ["commitment", "delegation", "failure"], "FAIL: profile sort"
    print("  Profile array sort: PASS")

    c = normalize_contract({"principals": [
        {"principal_id": "z:peer", "role": "m"},
        {"principal_id": "a:owner", "role": "o"}
    ]})
    assert c["principals"][0]["principal_id"] == "a:owner", "FAIL: principals sort"
    print("  Principals sort: PASS")

    print("\nAll verifications passed.")


if __name__ == "__main__":
    main()
