"""
tests/test_profiles.py — vincul.profiles test suite (unittest)
"""
import unittest

from vincul.profiles import (
    ComplianceProfile,
    ProfileStore,
    effective_bound,
    validate_profile,
    PROTOCOL_MAX_CONSTRAINT_ATOMS,
    PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH,
)

# Known-good CI vector hash for the minimal profile
KNOWN_PROFILE_HASH = "62fb2a4c1ea65dc2d7ce911168ccfc7d1791af16ad0dce3555d09cbe5db9d27a"


def make_minimal_profile(**overrides):
    """Build the pact-core-minimal-v0.2 profile (matches CI vector)."""
    kwargs = dict(
        profile_id="pact-core-minimal-v0.2",
        protocol_version="0.2",
        implementation={"name": "pact-reference", "version": "0.2.0", "vendor": None},
        bounds={
            "max_delegation_depth": 4,
            "max_scope_chain_length": 8,
            "revocation_resolution_deadline_ms": 5000,
            "ledger_snapshot_interval_seconds": None,
            "max_receipt_chain_fanout": None,
            "max_constraint_atoms": 32,
            "max_constraint_nesting_depth": 4,
        },
        supported_receipt_kinds=[
            "commitment", "contract_dissolution", "delegation",
            "failure", "revert_attempt", "revocation",
        ],
        supported_failure_codes=[
            "ANCESTOR_INVALID", "BUDGET_EXCEEDED", "CEILING_VIOLATED",
            "CONTRACT_DISSOLVED", "CONTRACT_EXPIRED", "CONTRACT_NOT_ACTIVE",
            "DELEGATION_MALFORMED", "DELEGATION_UNAUTHORIZED",
            "REVOCATION_STATE_UNRESOLVED", "REVOCATION_UNAUTHORIZED",
            "SCOPE_EXCEEDED", "SCOPE_EXPIRED", "SCOPE_REVOKED",
            "TYPE_ESCALATION", "UNKNOWN",
        ],
        signature_algorithms=["Ed25519"],
        attestation_schemas=None,
    )
    kwargs.update(overrides)
    return ComplianceProfile(**kwargs)


def make_simple_profile(profile_id="test-profile", **overrides):
    """Build a minimal valid profile for quick tests."""
    kwargs = dict(
        profile_id=profile_id,
        protocol_version="0.2",
        implementation={"name": "test", "version": "0.1.0", "vendor": None},
        bounds={
            "max_delegation_depth": 4,
            "max_constraint_atoms": 32,
            "max_constraint_nesting_depth": 4,
        },
        supported_receipt_kinds=["commitment", "failure"],
        supported_failure_codes=["UNKNOWN"],
        signature_algorithms=["Ed25519"],
        attestation_schemas=None,
    )
    kwargs.update(overrides)
    return ComplianceProfile(**kwargs)


# ── Hash and seal ────────────────────────────────────────────

class TestProfileHash(unittest.TestCase):
    def test_seal_sets_hash(self):
        p = make_minimal_profile()
        p.seal()
        self.assertIsNotNone(p.descriptor_hash)
        self.assertEqual(len(p.descriptor_hash), 64)

    def test_known_vector_hash(self):
        p = make_minimal_profile()
        p.seal()
        self.assertEqual(p.descriptor_hash, KNOWN_PROFILE_HASH)

    def test_verify_hash_passes(self):
        p = make_minimal_profile()
        p.seal()
        self.assertTrue(p.verify_hash())

    def test_verify_hash_fails_without_seal(self):
        p = make_minimal_profile()
        self.assertFalse(p.verify_hash())

    def test_hash_changes_with_different_bounds(self):
        p1 = make_minimal_profile()
        p1.seal()
        p2 = make_minimal_profile(bounds={
            "max_delegation_depth": 10,
            "max_constraint_atoms": 64,
            "max_constraint_nesting_depth": 8,
        })
        p2.seal()
        self.assertNotEqual(p1.descriptor_hash, p2.descriptor_hash)

    def test_hash_stable_across_array_order(self):
        """Normalization sorts arrays, so order shouldn't matter."""
        p1 = make_simple_profile(
            supported_receipt_kinds=["failure", "commitment"],
        )
        p1.seal()
        p2 = make_simple_profile(
            supported_receipt_kinds=["commitment", "failure"],
        )
        p2.seal()
        self.assertEqual(p1.descriptor_hash, p2.descriptor_hash)

    def test_hash_stable_across_failure_code_order(self):
        p1 = make_simple_profile(
            supported_failure_codes=["UNKNOWN", "SCOPE_REVOKED"],
        )
        p1.seal()
        p2 = make_simple_profile(
            supported_failure_codes=["SCOPE_REVOKED", "UNKNOWN"],
        )
        p2.seal()
        self.assertEqual(p1.descriptor_hash, p2.descriptor_hash)

    def test_hash_stable_across_algorithm_order(self):
        p1 = make_simple_profile(
            signature_algorithms=["Ed25519", "Ed448"],
        )
        p1.seal()
        p2 = make_simple_profile(
            signature_algorithms=["Ed448", "Ed25519"],
        )
        p2.seal()
        self.assertEqual(p1.descriptor_hash, p2.descriptor_hash)

    def test_hash_stable_across_attestation_schema_order(self):
        p1 = make_simple_profile(
            attestation_schemas=["pact.raw_bytes.v1", "stripe.payment_intent.v1"],
        )
        p1.seal()
        p2 = make_simple_profile(
            attestation_schemas=["stripe.payment_intent.v1", "pact.raw_bytes.v1"],
        )
        p2.seal()
        self.assertEqual(p1.descriptor_hash, p2.descriptor_hash)


# ── Serialization ────────────────────────────────────────────

class TestProfileSerialization(unittest.TestCase):
    def test_round_trip(self):
        original = make_minimal_profile()
        original.seal()
        restored = ComplianceProfile.from_dict(original.to_dict())
        self.assertEqual(restored.descriptor_hash, original.descriptor_hash)
        self.assertTrue(restored.verify_hash())

    def test_round_trip_with_attestation_schemas(self):
        original = make_simple_profile(
            attestation_schemas=["pact.raw_bytes.v1"],
        )
        original.seal()
        restored = ComplianceProfile.from_dict(original.to_dict())
        self.assertEqual(restored.attestation_schemas, ["pact.raw_bytes.v1"])
        self.assertTrue(restored.verify_hash())

    def test_to_dict_includes_descriptor_hash(self):
        p = make_minimal_profile()
        p.seal()
        d = p.to_dict()
        self.assertEqual(d["descriptor_hash"], p.descriptor_hash)

    def test_to_dict_without_seal(self):
        p = make_minimal_profile()
        d = p.to_dict()
        self.assertIsNone(d["descriptor_hash"])

    def test_from_dict_preserves_null_attestation_schemas(self):
        p = make_simple_profile(attestation_schemas=None)
        p.seal()
        restored = ComplianceProfile.from_dict(p.to_dict())
        self.assertIsNone(restored.attestation_schemas)

    def test_repr(self):
        p = make_minimal_profile()
        r = repr(p)
        self.assertIn("pact-core-minimal-v0.2", r)
        self.assertIn("0.2", r)


# ── Validation ───────────────────────────────────────────────

class TestProfileValidation(unittest.TestCase):
    def test_valid_profile_passes(self):
        p = make_minimal_profile()
        validate_profile(p)  # should not raise

    def test_max_constraint_atoms_at_limit(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": PROTOCOL_MAX_CONSTRAINT_ATOMS,
            "max_constraint_nesting_depth": 4,
        })
        validate_profile(p)  # exactly 64 is fine

    def test_max_constraint_atoms_exceeds_limit(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": PROTOCOL_MAX_CONSTRAINT_ATOMS + 1,
            "max_constraint_nesting_depth": 4,
        })
        with self.assertRaises(ValueError) as ctx:
            validate_profile(p)
        self.assertIn("max_constraint_atoms", str(ctx.exception))

    def test_max_constraint_nesting_depth_at_limit(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": 32,
            "max_constraint_nesting_depth": PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH,
        })
        validate_profile(p)  # exactly 8 is fine

    def test_max_constraint_nesting_depth_exceeds_limit(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": 32,
            "max_constraint_nesting_depth": PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH + 1,
        })
        with self.assertRaises(ValueError) as ctx:
            validate_profile(p)
        self.assertIn("max_constraint_nesting_depth", str(ctx.exception))

    def test_both_exceed_reports_atoms_first(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": 100,
            "max_constraint_nesting_depth": 20,
        })
        with self.assertRaises(ValueError) as ctx:
            validate_profile(p)
        self.assertIn("max_constraint_atoms", str(ctx.exception))

    def test_null_bounds_pass_validation(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": None,
            "max_constraint_nesting_depth": None,
        })
        validate_profile(p)  # null means not declared

    def test_tighter_bounds_pass(self):
        p = make_simple_profile(bounds={
            "max_constraint_atoms": 16,
            "max_constraint_nesting_depth": 2,
        })
        validate_profile(p)


# ── Effective bound (coalition interoperability) ─────────────

class TestEffectiveBound(unittest.TestCase):
    def test_most_restrictive_wins(self):
        p_a = make_simple_profile(
            profile_id="a",
            bounds={"max_delegation_depth": 10},
        )
        p_b = make_simple_profile(
            profile_id="b",
            bounds={"max_delegation_depth": 4},
        )
        self.assertEqual(effective_bound([p_a, p_b], "max_delegation_depth"), 4)

    def test_null_does_not_override_declared(self):
        p_a = make_simple_profile(
            profile_id="a",
            bounds={"max_delegation_depth": 10},
        )
        p_b = make_simple_profile(
            profile_id="b",
            bounds={"max_delegation_depth": None},
        )
        self.assertEqual(effective_bound([p_a, p_b], "max_delegation_depth"), 10)

    def test_all_null_returns_none(self):
        p_a = make_simple_profile(
            profile_id="a",
            bounds={"max_delegation_depth": None},
        )
        p_b = make_simple_profile(
            profile_id="b",
            bounds={"max_delegation_depth": None},
        )
        self.assertIsNone(effective_bound([p_a, p_b], "max_delegation_depth"))

    def test_single_profile(self):
        p = make_simple_profile(bounds={"max_delegation_depth": 7})
        self.assertEqual(effective_bound([p], "max_delegation_depth"), 7)

    def test_empty_list(self):
        self.assertIsNone(effective_bound([], "max_delegation_depth"))

    def test_three_profiles(self):
        profiles = [
            make_simple_profile(profile_id="a", bounds={"max_delegation_depth": 20}),
            make_simple_profile(profile_id="b", bounds={"max_delegation_depth": 4}),
            make_simple_profile(profile_id="c", bounds={"max_delegation_depth": 10}),
        ]
        self.assertEqual(effective_bound(profiles, "max_delegation_depth"), 4)

    def test_missing_bound_key_treated_as_none(self):
        p_a = make_simple_profile(
            profile_id="a",
            bounds={"max_delegation_depth": 5},
        )
        p_b = make_simple_profile(
            profile_id="b",
            bounds={},  # no max_delegation_depth key
        )
        self.assertEqual(effective_bound([p_a, p_b], "max_delegation_depth"), 5)


# ── ProfileStore ─────────────────────────────────────────────

class TestProfileStore(unittest.TestCase):
    def test_put_and_get(self):
        store = ProfileStore()
        p = make_simple_profile()
        store.put(p)
        self.assertIs(store.get("test-profile"), p)

    def test_put_seals_if_not_sealed(self):
        store = ProfileStore()
        p = make_simple_profile()
        self.assertIsNone(p.descriptor_hash)
        store.put(p)
        self.assertIsNotNone(p.descriptor_hash)
        self.assertTrue(p.verify_hash())

    def test_put_preserves_existing_seal(self):
        store = ProfileStore()
        p = make_simple_profile()
        p.seal()
        expected_hash = p.descriptor_hash
        store.put(p)
        self.assertEqual(p.descriptor_hash, expected_hash)

    def test_duplicate_profile_id_rejected(self):
        store = ProfileStore()
        store.put(make_simple_profile(profile_id="dup"))
        with self.assertRaises(ValueError) as ctx:
            store.put(make_simple_profile(profile_id="dup"))
        self.assertIn("Duplicate", str(ctx.exception))

    def test_get_nonexistent_returns_none(self):
        store = ProfileStore()
        self.assertIsNone(store.get("nonexistent"))

    def test_get_by_hash(self):
        store = ProfileStore()
        p = make_simple_profile()
        store.put(p)
        retrieved = store.get_by_hash(p.descriptor_hash)
        self.assertIs(retrieved, p)

    def test_get_by_hash_nonexistent(self):
        store = ProfileStore()
        self.assertIsNone(store.get_by_hash("a" * 64))

    def test_len(self):
        store = ProfileStore()
        self.assertEqual(len(store), 0)
        store.put(make_simple_profile(profile_id="a"))
        store.put(make_simple_profile(profile_id="b"))
        self.assertEqual(len(store), 2)

    def test_contains(self):
        store = ProfileStore()
        store.put(make_simple_profile(profile_id="x"))
        self.assertIn("x", store)
        self.assertNotIn("y", store)

    def test_validation_on_put(self):
        store = ProfileStore()
        bad = make_simple_profile(bounds={
            "max_constraint_atoms": 100,
            "max_constraint_nesting_depth": 4,
        })
        with self.assertRaises(ValueError):
            store.put(bad)
        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
