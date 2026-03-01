#!/usr/bin/env python3
"""
Pact Protocol — CI Vector Gate
ci/check_vectors.py

The first check in CI. Must pass before any other test runs.
Exit 0: all 13 vectors match — implementation is hash-correct.
Exit 1: any mismatch — do not merge.

Run: python3 ci/check_vectors.py
"""

import hashlib
import json
import sys

from pact.hashing import (
    pact_hash,
    pact_hash_constraint,
    normalize_contract,
    normalize_profile,
    normalize_ledger_balances,
)

# ── Expected vectors (source of truth: spec/crypto/HASHING.md §7) ──

EXPECTED: dict[str, str] = {
    "scope":                    "07992bbbbbc3e34126643faa78673b7e8db889ee9ff968c1f72d9e1625e7dba0",
    "contract_active":          "ea160e58b091116a5ecc87211265a1dafa1ae2f7fbc62d4ece6b706b798a9a08",
    "contract_dissolved":       "37809688c7636961fdb2a724e766aca88c5d2a46bd8db7860dcdfa7100e21fb6",
    "constraint_TOP":           "98047c362cd87227ccb70ff1635ba9fb68de6f3af390b5cf7b866af2ede53f44",
    "constraint_atom":          "dd07ce67ec196e23cf6a5ba26ba54a7aab1b4dd484fe96d656bd774245a4563a",
    "profile":                  "62fb2a4c1ea65dc2d7ce911168ccfc7d1791af16ad0dce3555d09cbe5db9d27a",
    "receipt_delegation":       "48f732e1d7a2a5c8a9a9195ab007f9e6dbef7dde21b3b4b482d785e66b9ed5d7",
    "receipt_commitment":       "723ae93f0f84f7e79874662ea52aebcda01aeaa7ee6bdbd08731d5df275faa72",
    "receipt_attestation":      "c3cd4ff294ce820f0cd25ba495ea29d32bbba77dc0621fdf0437afcce1c923b4",
    "receipt_ledger_snapshot":  "55fcced73b910cc08c43a4898090c00ab32409833947b6396be3f48914307573",
    "receipt_revocation":       "f36f7d210ec6aca062161a7f0f609498586888fc9d7f97ce25f05f9398fcedbb",
    "receipt_dissolution":      "97748e5f7a27d342f035ca996bfba15e349d1e4dd3107cd70c69c060d02cbb9e",
    "receipt_failure":          "da93e46a55e16f08395d3cc10477dcb3f784b9d88235778037d3a3bf5478722d",
}

# ── Fixtures (identical to tools/test_vectors/generate.py) ───

SCOPE = {
    "id": "00000000-0000-0000-0000-000000000001",
    "issued_by_scope_id": None, "issued_by": "principal:test",
    "issued_at": "2025-01-01T00:00:00Z", "expires_at": None,
    "domain": {"namespace": "test.resource", "types": ["OBSERVE"]},
    "predicate": "TOP", "ceiling": "TOP",
    "delegate": False, "revoke": "principal_only",
    "status": "active", "effective_at": None,
}

CONTRACT = {
    "contract_id": "00000000-0000-0000-0000-000000000003",
    "version": "0.1",
    "purpose": {"title": "Test Coalition",
                "description": "Minimal coalition for test vector generation",
                "expires_at": None},
    "principals": [
        {"principal_id": "principal:test", "role": "owner", "revoke_right": True},
        {"principal_id": "principal:peer", "role": "member", "revoke_right": False},
    ],
    "governance": {
        "decision_rule": "unanimous", "threshold": None,
        "signatory_policy": {
            "delegation":     {"required_signers": ["delegator"]},
            "commitment":     {"required_signers": ["initiator"]},
            "revocation":     {"required_signers": ["principal"]},
            "revert_attempt": {"required_signers": ["initiator"]},
            "failure":        {"required_signers": []},
            "dissolution":    {"required_signers": ["principal"]},
        },
    },
    "budget_policy": {"allowed": False, "dimensions": None, "per_principal_limit": None},
    "activation": {"status": "active", "activated_at": "2025-01-01T00:00:00Z", "dissolved_at": None},
}

PROFILE = {
    "profile_id": "pact-core-minimal-v0.2",
    "protocol_version": "0.2",
    "implementation": {"name": "pact-reference", "version": "0.2.0", "vendor": None},
    "bounds": {
        "max_delegation_depth": 4, "max_scope_chain_length": 8,
        "revocation_resolution_deadline_ms": 5000,
        "ledger_snapshot_interval_seconds": None, "max_receipt_chain_fanout": None,
        "max_constraint_atoms": 32, "max_constraint_nesting_depth": 4,
    },
    "supported_receipt_kinds": [
        "commitment", "contract_dissolution", "delegation",
        "failure", "revert_attempt", "revocation",
    ],
    "supported_failure_codes": [
        "ANCESTOR_INVALID", "BUDGET_EXCEEDED", "CEILING_VIOLATED",
        "CONTRACT_DISSOLVED", "CONTRACT_EXPIRED", "CONTRACT_NOT_ACTIVE",
        "DELEGATION_MALFORMED", "DELEGATION_UNAUTHORIZED",
        "REVOCATION_STATE_UNRESOLVED", "REVOCATION_UNAUTHORIZED",
        "SCOPE_EXCEEDED", "SCOPE_EXPIRED", "SCOPE_REVOKED",
        "TYPE_ESCALATION", "UNKNOWN",
    ],
    "signature_algorithms": ["Ed25519"],
    "attestation_schemas": None,
}


def make_receipt(receipt_id, kind, issued_at, action, description,
                 initiated_by, scope_id, scope_hash, contract_id,
                 contract_hash, signatories, outcome, detail, prior_receipt=None):
    return {
        "receipt_id": receipt_id, "receipt_kind": kind, "issued_at": issued_at,
        "intent": {"action": action, "description": description, "initiated_by": initiated_by},
        "authority": {
            "scope_id": scope_id, "scope_hash": scope_hash,
            "contract_id": contract_id, "contract_hash": contract_hash,
            "signatories": signatories,
        },
        "result": {"outcome": outcome, "detail": detail},
        "prior_receipt": prior_receipt,
    }


def run() -> int:
    failures: list[tuple[str, str, str]] = []

    def check(name: str, got: str) -> None:
        if got != EXPECTED[name]:
            failures.append((name, EXPECTED[name], got))

    # Object hashes
    scope_hash = pact_hash("scope", SCOPE)
    check("scope", scope_hash)

    contract_norm = normalize_contract(CONTRACT)
    contract_hash = pact_hash("contract", contract_norm)
    check("contract_active", contract_hash)

    dissolved = json.loads(json.dumps(contract_norm))
    dissolved["activation"]["status"] = "dissolved"
    dissolved["activation"]["dissolved_at"] = "2025-01-01T02:00:00Z"
    dissolved_hash = pact_hash("contract", dissolved)
    check("contract_dissolved", dissolved_hash)

    check("constraint_TOP",  pact_hash_constraint("TOP"))
    check("constraint_atom", pact_hash_constraint("action.params.duration_minutes <= 60"))
    check("profile",         pact_hash("profile", normalize_profile(PROFILE)))

    top_hash = pact_hash_constraint("TOP")

    # delegation
    delegation = make_receipt(
        "00000000-0000-0000-0000-000000000002", "delegation",
        "2025-01-01T00:01:00Z", "delegate",
        "Delegate OBSERVE on test.resource to agent:child", "principal:test",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:test"], "success",
        {"child_scope_id": "00000000-0000-0000-0000-000000000004",
         "child_scope_hash": scope_hash,
         "parent_scope_id": "00000000-0000-0000-0000-000000000001",
         "types_granted": ["OBSERVE"], "delegate_granted": False,
         "revoke_granted": "principal_only", "expires_at": None,
         "ceiling_hash": top_hash},
    )
    delegation_hash = pact_hash("receipt", delegation)
    check("receipt_delegation", delegation_hash)

    # commitment
    commitment = make_receipt(
        "00000000-0000-0000-0000-000000000005", "commitment",
        "2025-01-01T00:02:00Z", "commit",
        "Create event:00000001 on test.resource", "principal:test",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:test"], "success",
        {"action_type": "COMMIT", "namespace": "test.resource",
         "resource": "event:00000001", "params": {"duration_minutes": 60},
         "reversible": True, "revert_window": "PT10M",
         "external_ref": "ext:booking:abc123", "budget_consumed": None},
    )
    commitment_hash = pact_hash("receipt", commitment)
    check("receipt_commitment", commitment_hash)

    # attestation
    response_hash_value = hashlib.sha256(
        b'{"id":"booking:abc123","status":"confirmed"}'
    ).hexdigest()
    attestation = make_receipt(
        "00000000-0000-0000-0000-000000000006", "attestation",
        "2025-01-01T00:02:10Z", "attest",
        "Attest booking confirmation for commitment 00000000-0000-0000-0000-000000000005",
        "principal:peer",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:peer"], "success",
        {"attests_receipt_id": "00000000-0000-0000-0000-000000000005",
         "attests_receipt_hash": commitment_hash,
         "response_hash": {"algo": "sha256", "value": response_hash_value},
         "response_schema": "test.booking.v1",
         "external_ref": "ext:booking:abc123",
         "produced_at": "2025-01-01T00:02:05Z"},
        prior_receipt=commitment_hash,
    )
    check("receipt_attestation", pact_hash("receipt", attestation))

    # ledger_snapshot
    balances = normalize_ledger_balances([{
        "dimension": "GBP", "ceiling": 100.00, "consumed": 9.99,
        "remaining": 90.01, "commitment_count": 1,
    }])
    ledger = make_receipt(
        "00000000-0000-0000-0000-000000000007", "ledger_snapshot",
        "2025-01-01T01:00:00Z", "ledger_snapshot",
        "Revocation-time ledger snapshot for scope 00000000-0000-0000-0000-000000000001",
        "principal:test",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:test"], "success",
        {"snapshot_type": "revocation",
         "covers_scope_id": "00000000-0000-0000-0000-000000000001",
         "snapshot_period": {"from": "2025-01-01T00:00:00Z", "to": "2025-01-01T01:00:00Z"},
         "balances": balances, "prior_snapshot": None,
         "commitment_refs": ["00000000-0000-0000-0000-000000000005"]},
    )
    check("receipt_ledger_snapshot", pact_hash("receipt", ledger))

    # revocation
    revocation = make_receipt(
        "00000000-0000-0000-0000-000000000009", "revocation",
        "2025-01-01T01:00:00Z", "revoke",
        "Revoke scope 00000000-0000-0000-0000-000000000001", "principal:test",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:test"], "success",
        {"revocation_root": "00000000-0000-0000-0000-000000000001",
         "revoked_by": "principal:test", "authority_type": "principal",
         "effective_at": "2025-01-01T01:00:00Z",
         "cascade_method": "root+proof", "revert_attempts": [], "non_revertable": []},
    )
    revocation_hash = pact_hash("receipt", revocation)
    check("receipt_revocation", revocation_hash)

    # contract_dissolution
    dissolution = make_receipt(
        "00000000-0000-0000-0000-000000000008", "contract_dissolution",
        "2025-01-01T02:00:00Z", "dissolve_contract",
        "Coalition dissolved by unanimous decision", "principal:test",
        None, None,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        ["principal:peer", "principal:test"], "success",
        {"contract_id": "00000000-0000-0000-0000-000000000003",
         "contract_hash_before": contract_hash,
         "contract_hash_after": dissolved_hash,
         "dissolved_at": "2025-01-01T02:00:00Z",
         "dissolved_by": "principal:test",
         "decision_rule": "unanimous", "signatures_present": 2,
         "ledger_snapshot_hash": None},
    )
    check("receipt_dissolution", pact_hash("receipt", dissolution))

    # failure
    failure = make_receipt(
        "00000000-0000-0000-0000-000000000010", "failure",
        "2025-01-01T01:05:00Z", "fail",
        "Action denied: scope has been revoked", "principal:test",
        "00000000-0000-0000-0000-000000000001", scope_hash,
        "00000000-0000-0000-0000-000000000003", contract_hash,
        [], "failure",
        {"error_code": "SCOPE_REVOKED",
         "message": "This scope was revoked by principal:test at 2025-01-01T01:00:00Z.",
         "recoverable": False,
         "scope_id": "00000000-0000-0000-0000-000000000001",
         "scope_hash": scope_hash,
         "contract_id": "00000000-0000-0000-0000-000000000003",
         "contract_hash": contract_hash,
         "revocation_root_scope_id": "00000000-0000-0000-0000-000000000001",
         "effective_at": "2025-01-01T01:00:00Z",
         "revocation_receipt_hash": revocation_hash},
        prior_receipt=revocation_hash,
    )
    check("receipt_failure", pact_hash("receipt", failure))

    # ── Report ────────────────────────────────────────────────
    total = len(EXPECTED)
    passed = total - len(failures)

    print(f"\nPact CI Vector Gate")
    print(f"{'=' * 50}")
    print(f"Protocol version: v0.2")
    print(f"Vectors checked:  {total}")
    print(f"Passed:           {passed}")
    print(f"Failed:           {len(failures)}")

    if failures:
        print("\nFAILURES:")
        for name, expected, got in failures:
            print(f"\n  [{name}]")
            print(f"    expected: {expected}")
            print(f"    got:      {got}")
        print("\n❌ CI gate FAILED — do not merge")
        return 1

    print("\n✅ All vectors match — implementation is hash-correct")
    return 0


if __name__ == "__main__":
    sys.exit(run())
