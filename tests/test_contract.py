"""
tests/test_contract.py — pact.contract test suite (unittest)

Covers COALITION.md invariants, lifecycle state machine, governance rules,
hashing determinism, and ContractStoreProtocol conformance.
"""

import json
import unittest
from datetime import datetime, timezone, timedelta

from pact.contract import (
    CoalitionContract, ContractStore,
    validate_contract, check_governance,
)
from pact.hashing import pact_hash, normalize_contract
from pact.types import ContractStatus, DecisionRule


# ── Fixtures ──────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def ts(offset_seconds: int = 0) -> str:
    t = _now() + timedelta(seconds=offset_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


DEFAULT_SIGNATORY_POLICY = {
    "delegation":     {"required_signers": ["delegator"]},
    "commitment":     {"required_signers": ["initiator"]},
    "revocation":     {"required_signers": ["principal"]},
    "revert_attempt": {"required_signers": ["initiator"]},
    "failure":        {"required_signers": []},
    "dissolution":    {"required_signers": ["principal"]},
}


def make_contract(
    contract_id: str = "contract-001",
    version: str = "0.1",
    title: str = "Test Coalition",
    description: str = "A test coalition",
    expires_at: str | None = None,
    principals: list[dict] | None = None,
    decision_rule: str = "unanimous",
    threshold: int | None = None,
    budget_allowed: bool = False,
    budget_dimensions: list[str] | None = None,
    per_principal_limit: dict | None = None,
    status: str = "draft",
    activated_at: str | None = None,
    dissolved_at: str | None = None,
) -> CoalitionContract:
    if principals is None:
        principals = [
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
            {"principal_id": "principal:bob", "role": "member", "revoke_right": False},
        ]
    return CoalitionContract(
        contract_id=contract_id,
        version=version,
        purpose={"title": title, "description": description, "expires_at": expires_at},
        principals=principals,
        governance={
            "decision_rule": decision_rule,
            "threshold": threshold,
            "signatory_policy": DEFAULT_SIGNATORY_POLICY,
        },
        budget_policy={
            "allowed": budget_allowed,
            "dimensions": budget_dimensions,
            "per_principal_limit": per_principal_limit,
        },
        activation={
            "status": status,
            "activated_at": activated_at,
            "dissolved_at": dissolved_at,
        },
    )


def make_active_contract(**kwargs) -> CoalitionContract:
    """A contract already in active status."""
    defaults = {"status": "active", "activated_at": ts(-3600)}
    defaults.update(kwargs)
    return make_contract(**defaults)


ALL_PRINCIPAL_IDS = ["principal:alice", "principal:bob"]


# ═════════════════════════════════════════════════════════════
# §1: Contract Schema and Structural Validation
# ═════════════════════════════════════════════════════════════

class TestContractSchema(unittest.TestCase):
    """COALITION.md §2 — schema structure and invariant 12."""

    def test_minimum_two_principals(self):
        """Invariant 12: single-principal contracts are malformed."""
        c = make_contract(principals=[
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
        ])
        with self.assertRaises(ValueError, msg="at least 2 principals"):
            validate_contract(c)

    def test_two_principals_valid(self):
        c = make_contract()
        validate_contract(c)  # should not raise

    def test_empty_principals_invalid(self):
        c = make_contract(principals=[])
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_duplicate_principal_ids_invalid(self):
        c = make_contract(principals=[
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
            {"principal_id": "principal:alice", "role": "member", "revoke_right": False},
        ])
        with self.assertRaises(ValueError, msg="Duplicate"):
            validate_contract(c)

    def test_empty_title_invalid(self):
        c = make_contract(title="")
        with self.assertRaises(ValueError, msg="title"):
            validate_contract(c)

    def test_whitespace_only_title_invalid(self):
        c = make_contract(title="   ")
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_threshold_present_when_rule_is_threshold(self):
        c = make_contract(decision_rule="threshold", threshold=2)
        validate_contract(c)  # should not raise

    def test_threshold_missing_when_rule_is_threshold(self):
        c = make_contract(decision_rule="threshold", threshold=None)
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_threshold_zero_invalid(self):
        c = make_contract(decision_rule="threshold", threshold=0)
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_threshold_exceeds_principals_invalid(self):
        c = make_contract(decision_rule="threshold", threshold=5)
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_threshold_present_when_rule_is_unanimous_invalid(self):
        c = make_contract(decision_rule="unanimous", threshold=2)
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_unknown_decision_rule_invalid(self):
        c = make_contract(decision_rule="supermajority")
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_budget_dimensions_null_when_not_allowed(self):
        c = make_contract(budget_allowed=False, budget_dimensions=None)
        validate_contract(c)  # should not raise

    def test_budget_dimensions_present_when_not_allowed_invalid(self):
        c = make_contract(budget_allowed=False, budget_dimensions=["EUR"])
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_budget_dimensions_null_when_allowed_invalid(self):
        c = make_contract(budget_allowed=True, budget_dimensions=None)
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_budget_dimensions_empty_when_allowed_invalid(self):
        c = make_contract(budget_allowed=True, budget_dimensions=[])
        with self.assertRaises(ValueError):
            validate_contract(c)

    def test_budget_dimensions_when_allowed(self):
        c = make_contract(budget_allowed=True, budget_dimensions=["EUR", "USD"])
        validate_contract(c)  # should not raise


# ═════════════════════════════════════════════════════════════
# §2: Contract Hashing
# ═════════════════════════════════════════════════════════════

class TestContractHashing(unittest.TestCase):
    """COALITION.md invariants 7, 13, 14 — hashing determinism and normalization."""

    def test_seal_sets_descriptor_hash(self):
        c = make_contract()
        self.assertIsNone(c.descriptor_hash)
        c.seal()
        self.assertIsNotNone(c.descriptor_hash)
        self.assertEqual(len(c.descriptor_hash), 64)

    def test_hash_deterministic(self):
        c1 = make_contract()
        c2 = make_contract()
        self.assertEqual(c1.compute_hash(), c2.compute_hash())

    def test_principals_sorted_before_hashing(self):
        """Invariant 13: unsorted principals produce same hash as sorted."""
        c_sorted = make_contract(principals=[
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
            {"principal_id": "principal:bob", "role": "member", "revoke_right": False},
        ])
        c_unsorted = make_contract(principals=[
            {"principal_id": "principal:bob", "role": "member", "revoke_right": False},
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
        ])
        self.assertEqual(c_sorted.compute_hash(), c_unsorted.compute_hash())

    def test_hash_matches_ci_vector(self):
        """Hash must match the CI vector for the active contract."""
        c = CoalitionContract(
            contract_id="00000000-0000-0000-0000-000000000003",
            version="0.1",
            purpose={
                "title": "Test Coalition",
                "description": "Minimal coalition for test vector generation",
                "expires_at": None,
            },
            principals=[
                {"principal_id": "principal:test", "role": "owner", "revoke_right": True},
                {"principal_id": "principal:peer", "role": "member", "revoke_right": False},
            ],
            governance={
                "decision_rule": "unanimous",
                "threshold": None,
                "signatory_policy": {
                    "delegation":     {"required_signers": ["delegator"]},
                    "commitment":     {"required_signers": ["initiator"]},
                    "revocation":     {"required_signers": ["principal"]},
                    "revert_attempt": {"required_signers": ["initiator"]},
                    "failure":        {"required_signers": []},
                    "dissolution":    {"required_signers": ["principal"]},
                },
            },
            budget_policy={"allowed": False, "dimensions": None, "per_principal_limit": None},
            activation={"status": "active", "activated_at": "2025-01-01T00:00:00Z", "dissolved_at": None},
        )
        self.assertEqual(
            c.compute_hash(),
            "ea160e58b091116a5ecc87211265a1dafa1ae2f7fbc62d4ece6b706b798a9a08",
        )

    def test_lifecycle_changes_hash(self):
        """Invariant 14: hash changes on activation.status transitions."""
        c = make_contract(status="active", activated_at="2025-01-01T00:00:00Z")
        c.seal()
        hash_active = c.descriptor_hash

        c.activation["status"] = "dissolved"
        c.activation["dissolved_at"] = "2025-01-01T02:00:00Z"
        c.seal()
        hash_dissolved = c.descriptor_hash

        self.assertNotEqual(hash_active, hash_dissolved)

    def test_different_contracts_different_hashes(self):
        c1 = make_contract(title="Alpha")
        c2 = make_contract(title="Beta")
        self.assertNotEqual(c1.compute_hash(), c2.compute_hash())

    def test_verify_hash_passes(self):
        c = make_contract()
        c.seal()
        self.assertTrue(c.verify_hash())

    def test_verify_hash_fails_after_tamper(self):
        c = make_contract()
        c.seal()
        c.purpose["title"] = "Tampered"
        self.assertFalse(c.verify_hash())

    def test_verify_hash_fails_when_unsealed(self):
        c = make_contract()
        self.assertFalse(c.verify_hash())


# ═════════════════════════════════════════════════════════════
# §3: Serialization Round-Trip
# ═════════════════════════════════════════════════════════════

class TestContractSerialization(unittest.TestCase):

    def test_round_trip(self):
        c = make_contract()
        c.seal()
        d = c.to_dict()
        restored = CoalitionContract.from_dict(d)
        self.assertEqual(restored.contract_id, c.contract_id)
        self.assertEqual(restored.descriptor_hash, c.descriptor_hash)
        self.assertTrue(restored.verify_hash())

    def test_hash_reproducible_after_round_trip(self):
        c = make_contract()
        c.seal()
        restored = CoalitionContract.from_dict(c.to_dict())
        self.assertEqual(restored.compute_hash(), c.descriptor_hash)

    def test_repr(self):
        c = make_contract()
        r = repr(c)
        self.assertIn("contract-001", r)
        self.assertIn("draft", r)


# ═════════════════════════════════════════════════════════════
# §4: Governance Signature Checks
# ═════════════════════════════════════════════════════════════

class TestGovernance(unittest.TestCase):
    """COALITION.md §3 — decision rule enforcement, invariant 9."""

    def test_unanimous_all_signed(self):
        c = make_contract(decision_rule="unanimous")
        self.assertTrue(check_governance(c, ["principal:alice", "principal:bob"]))

    def test_unanimous_one_missing(self):
        c = make_contract(decision_rule="unanimous")
        self.assertFalse(check_governance(c, ["principal:alice"]))

    def test_unanimous_none_signed(self):
        c = make_contract(decision_rule="unanimous")
        self.assertFalse(check_governance(c, []))

    def test_majority_with_two_principals(self):
        """2 principals: majority requires > 1, so both must sign."""
        c = make_contract(decision_rule="majority")
        self.assertFalse(check_governance(c, ["principal:alice"]))
        self.assertTrue(check_governance(c, ["principal:alice", "principal:bob"]))

    def test_majority_with_three_principals(self):
        """3 principals: majority requires > 1.5, so 2 suffice."""
        c = make_contract(
            decision_rule="majority",
            principals=[
                {"principal_id": "principal:a", "role": "owner", "revoke_right": True},
                {"principal_id": "principal:b", "role": "member", "revoke_right": False},
                {"principal_id": "principal:c", "role": "member", "revoke_right": False},
            ],
        )
        self.assertTrue(check_governance(c, ["principal:a", "principal:b"]))
        self.assertFalse(check_governance(c, ["principal:a"]))

    def test_threshold(self):
        c = make_contract(
            decision_rule="threshold",
            threshold=1,
        )
        self.assertTrue(check_governance(c, ["principal:alice"]))
        self.assertTrue(check_governance(c, ["principal:alice", "principal:bob"]))

    def test_threshold_not_met(self):
        c = make_contract(decision_rule="threshold", threshold=2)
        self.assertFalse(check_governance(c, ["principal:alice"]))

    def test_duplicate_signatures_count_once(self):
        """Invariant 9: duplicate principal signatures count once."""
        c = make_contract(decision_rule="unanimous")
        self.assertFalse(check_governance(
            c, ["principal:alice", "principal:alice", "principal:alice"]
        ))

    def test_unknown_signers_ignored(self):
        """Signatures from non-principals are ignored."""
        c = make_contract(decision_rule="unanimous")
        self.assertFalse(check_governance(
            c, ["principal:alice", "principal:unknown"]
        ))

    def test_unknown_signers_do_not_count(self):
        c = make_contract(decision_rule="threshold", threshold=1)
        self.assertFalse(check_governance(c, ["principal:stranger"]))


# ═════════════════════════════════════════════════════════════
# §5: ContractStore — Basic Operations
# ═════════════════════════════════════════════════════════════

class TestContractStore(unittest.TestCase):

    def test_put_and_get(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)
        self.assertIs(store.get("contract-001"), c)

    def test_put_seals_contract(self):
        store = ContractStore()
        c = make_contract()
        self.assertIsNone(c.descriptor_hash)
        store.put(c)
        self.assertIsNotNone(c.descriptor_hash)

    def test_get_by_hash(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)
        self.assertIs(store.get_by_hash(c.descriptor_hash), c)

    def test_get_nonexistent_returns_none(self):
        store = ContractStore()
        self.assertIsNone(store.get("nonexistent"))

    def test_get_by_hash_nonexistent_returns_none(self):
        store = ContractStore()
        self.assertIsNone(store.get_by_hash("a" * 64))

    def test_duplicate_contract_id_raises(self):
        store = ContractStore()
        store.put(make_contract())
        with self.assertRaises(ValueError, msg="Duplicate"):
            store.put(make_contract())

    def test_structural_validation_on_put(self):
        store = ContractStore()
        c = make_contract(principals=[
            {"principal_id": "principal:only", "role": "owner", "revoke_right": True},
        ])
        with self.assertRaises(ValueError):
            store.put(c)

    def test_len_and_contains(self):
        store = ContractStore()
        self.assertEqual(len(store), 0)
        self.assertNotIn("contract-001", store)
        store.put(make_contract())
        self.assertEqual(len(store), 1)
        self.assertIn("contract-001", store)


# ═════════════════════════════════════════════════════════════
# §6: Activation Lifecycle
# ═════════════════════════════════════════════════════════════

class TestActivation(unittest.TestCase):
    """COALITION.md §4 — draft → active transition, invariant 1."""

    def test_activate_draft_to_active(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)

        before, after = store.activate(
            "contract-001", ts(0), ALL_PRINCIPAL_IDS,
        )
        self.assertEqual(before.activation["status"], "draft")
        self.assertEqual(after.activation["status"], "active")
        self.assertTrue(after.is_active())

    def test_activate_changes_hash(self):
        """Invariant 14: hash changes on lifecycle transition."""
        store = ContractStore()
        c = make_contract()
        store.put(c)
        hash_draft = c.descriptor_hash

        _, after = store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        self.assertNotEqual(hash_draft, after.descriptor_hash)

    def test_activate_updates_hash_index(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)
        hash_draft = c.descriptor_hash

        _, after = store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        # Old hash no longer resolves
        self.assertIsNone(store.get_by_hash(hash_draft))
        # New hash resolves
        self.assertIs(store.get_by_hash(after.descriptor_hash), after)

    def test_activate_sets_activated_at(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)
        activated_at = ts(0)

        _, after = store.activate("contract-001", activated_at, ALL_PRINCIPAL_IDS)
        self.assertEqual(after.activation["activated_at"], activated_at)

    def test_activate_requires_draft_status(self):
        store = ContractStore()
        c = make_active_contract()
        store.put(c)
        with self.assertRaises(ValueError, msg="expected 'draft'"):
            store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)

    def test_activate_requires_governance(self):
        store = ContractStore()
        c = make_contract()
        store.put(c)
        with self.assertRaises(ValueError, msg="governance"):
            store.activate("contract-001", ts(0), ["principal:alice"])

    def test_double_activate_rejected(self):
        """Invariant 1: contracts are immutable after activation."""
        store = ContractStore()
        c = make_contract()
        store.put(c)
        store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        with self.assertRaises(ValueError):
            store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)

    def test_activate_nonexistent_raises(self):
        store = ContractStore()
        with self.assertRaises(KeyError):
            store.activate("nonexistent", ts(0), ALL_PRINCIPAL_IDS)

    def test_before_snapshot_is_independent(self):
        """The before snapshot must not be affected by mutations to the contract."""
        store = ContractStore()
        c = make_contract()
        store.put(c)
        before, after = store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        self.assertEqual(before.activation["status"], "draft")
        self.assertEqual(after.activation["status"], "active")
        # Verify before has its own hash
        self.assertTrue(before.verify_hash())


# ═════════════════════════════════════════════════════════════
# §7: Dissolution Lifecycle
# ═════════════════════════════════════════════════════════════

class TestDissolution(unittest.TestCase):
    """COALITION.md §5 — dissolution rules, invariant 5."""

    def _activate_contract(self, store: ContractStore, contract_id: str = "contract-001"):
        store.activate(contract_id, ts(-60), ALL_PRINCIPAL_IDS)

    def test_dissolve_active_to_dissolved(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)

        before, after = store.dissolve(
            "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
        )
        self.assertEqual(before.activation["status"], "active")
        self.assertEqual(after.activation["status"], "dissolved")
        self.assertTrue(after.is_dissolved())

    def test_dissolve_changes_hash(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        c = store.get("contract-001")
        hash_active = c.descriptor_hash

        _, after = store.dissolve(
            "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
        )
        self.assertNotEqual(hash_active, after.descriptor_hash)

    def test_dissolve_updates_hash_index(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        c = store.get("contract-001")
        hash_active = c.descriptor_hash

        _, after = store.dissolve(
            "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
        )
        self.assertIsNone(store.get_by_hash(hash_active))
        self.assertIs(store.get_by_hash(after.descriptor_hash), after)

    def test_dissolve_sets_dissolved_at(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        dissolved_at = ts(0)

        _, after = store.dissolve(
            "contract-001", dissolved_at, "principal:alice", ALL_PRINCIPAL_IDS,
        )
        self.assertEqual(after.activation["dissolved_at"], dissolved_at)

    def test_dissolve_requires_active_status(self):
        """Cannot dissolve a draft contract."""
        store = ContractStore()
        store.put(make_contract())
        with self.assertRaises(ValueError, msg="expected 'active'"):
            store.dissolve(
                "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
            )

    def test_dissolve_requires_governance(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        with self.assertRaises(ValueError, msg="governance"):
            store.dissolve(
                "contract-001", ts(0), "principal:alice", ["principal:alice"],
            )

    def test_dissolution_is_terminal(self):
        """Invariant 5: no amendment or reactivation after dissolution."""
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        store.dissolve("contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS)

        # Cannot dissolve again
        with self.assertRaises(ValueError):
            store.dissolve(
                "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
            )
        # Cannot activate a dissolved contract
        with self.assertRaises(ValueError):
            store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)

    def test_dissolve_nonexistent_raises(self):
        store = ContractStore()
        with self.assertRaises(KeyError):
            store.dissolve("nonexistent", ts(0), "principal:alice", ALL_PRINCIPAL_IDS)

    def test_before_snapshot_is_independent(self):
        store = ContractStore()
        store.put(make_contract())
        self._activate_contract(store)
        before, after = store.dissolve(
            "contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS,
        )
        self.assertEqual(before.activation["status"], "active")
        self.assertEqual(after.activation["status"], "dissolved")
        self.assertTrue(before.verify_hash())

    def test_dissolution_hash_matches_ci_vector(self):
        """The dissolved hash must match the CI vector."""
        c = CoalitionContract(
            contract_id="00000000-0000-0000-0000-000000000003",
            version="0.1",
            purpose={
                "title": "Test Coalition",
                "description": "Minimal coalition for test vector generation",
                "expires_at": None,
            },
            principals=[
                {"principal_id": "principal:test", "role": "owner", "revoke_right": True},
                {"principal_id": "principal:peer", "role": "member", "revoke_right": False},
            ],
            governance={
                "decision_rule": "unanimous",
                "threshold": None,
                "signatory_policy": {
                    "delegation":     {"required_signers": ["delegator"]},
                    "commitment":     {"required_signers": ["initiator"]},
                    "revocation":     {"required_signers": ["principal"]},
                    "revert_attempt": {"required_signers": ["initiator"]},
                    "failure":        {"required_signers": []},
                    "dissolution":    {"required_signers": ["principal"]},
                },
            },
            budget_policy={"allowed": False, "dimensions": None, "per_principal_limit": None},
            activation={
                "status": "dissolved",
                "activated_at": "2025-01-01T00:00:00Z",
                "dissolved_at": "2025-01-01T02:00:00Z",
            },
        )
        self.assertEqual(
            c.compute_hash(),
            "37809688c7636961fdb2a724e766aca88c5d2a46bd8db7860dcdfa7100e21fb6",
        )


# ═════════════════════════════════════════════════════════════
# §8: Expiry
# ═════════════════════════════════════════════════════════════

class TestExpiry(unittest.TestCase):
    """COALITION.md §4 — expiry is a condition, not an event (invariant 4)."""

    def test_no_expiry_is_valid(self):
        c = make_active_contract(expires_at=None)
        self.assertFalse(c.is_expired_by_clock())
        self.assertTrue(c.is_valid())

    def test_future_expiry_is_valid(self):
        c = make_active_contract(expires_at=ts(+3600))
        self.assertFalse(c.is_expired_by_clock())
        self.assertTrue(c.is_valid())

    def test_past_expiry_is_expired(self):
        c = make_active_contract(expires_at=ts(-60))
        self.assertTrue(c.is_expired_by_clock())
        self.assertFalse(c.is_valid())

    def test_draft_is_not_valid(self):
        c = make_contract()
        self.assertFalse(c.is_valid())

    def test_dissolved_is_not_valid(self):
        c = make_active_contract()
        c.activation["status"] = "dissolved"
        c.activation["dissolved_at"] = ts(-60)
        self.assertFalse(c.is_valid())

    def test_is_valid_checks_dissolved_at(self):
        """A contract with dissolved_at set but status still 'active' is invalid."""
        c = make_active_contract()
        c.activation["dissolved_at"] = ts(-60)
        self.assertFalse(c.is_valid())


# ═════════════════════════════════════════════════════════════
# §9: Status Queries
# ═════════════════════════════════════════════════════════════

class TestStatusQueries(unittest.TestCase):

    def test_is_active(self):
        c = make_active_contract()
        self.assertTrue(c.is_active())
        self.assertFalse(c.is_dissolved())
        self.assertFalse(c.is_draft())

    def test_is_draft(self):
        c = make_contract()
        self.assertTrue(c.is_draft())
        self.assertFalse(c.is_active())

    def test_is_dissolved(self):
        c = make_active_contract()
        c.activation["status"] = "dissolved"
        self.assertTrue(c.is_dissolved())

    def test_status_property(self):
        c = make_contract()
        self.assertEqual(c.status, ContractStatus.DRAFT)
        c.activation["status"] = "active"
        self.assertEqual(c.status, ContractStatus.ACTIVE)

    def test_store_is_active(self):
        store = ContractStore()
        store.put(make_contract())
        self.assertFalse(store.is_active("contract-001"))
        store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        self.assertTrue(store.is_active("contract-001"))

    def test_store_is_dissolved(self):
        store = ContractStore()
        store.put(make_contract())
        store.activate("contract-001", ts(0), ALL_PRINCIPAL_IDS)
        self.assertFalse(store.is_dissolved("contract-001"))
        store.dissolve("contract-001", ts(0), "principal:alice", ALL_PRINCIPAL_IDS)
        self.assertTrue(store.is_dissolved("contract-001"))

    def test_store_queries_nonexistent_return_false(self):
        store = ContractStore()
        self.assertFalse(store.is_active("nonexistent"))
        self.assertFalse(store.is_dissolved("nonexistent"))


# ═════════════════════════════════════════════════════════════
# §10: Principal Helpers
# ═════════════════════════════════════════════════════════════

class TestPrincipalHelpers(unittest.TestCase):

    def test_principal_ids_sorted(self):
        c = make_contract(principals=[
            {"principal_id": "principal:bob", "role": "member", "revoke_right": False},
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
        ])
        self.assertEqual(c.principal_ids(), ["principal:alice", "principal:bob"])

    def test_has_principal(self):
        c = make_contract()
        self.assertTrue(c.has_principal("principal:alice"))
        self.assertFalse(c.has_principal("principal:unknown"))

    def test_get_principal(self):
        c = make_contract()
        p = c.get_principal("principal:alice")
        self.assertIsNotNone(p)
        self.assertEqual(p["role"], "owner")
        self.assertIsNone(c.get_principal("principal:unknown"))


# ═════════════════════════════════════════════════════════════
# §11: Protocol Conformance
# ═════════════════════════════════════════════════════════════

class TestContractStoreProtocol(unittest.TestCase):
    """Verify ContractStore satisfies ContractStoreProtocol."""

    def test_isinstance_check(self):
        from pact.interfaces import ContractStoreProtocol
        store = ContractStore()
        self.assertIsInstance(store, ContractStoreProtocol)


if __name__ == "__main__":
    unittest.main()
