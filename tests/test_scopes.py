"""
tests/test_scopes.py — pact.scopes test suite (unittest)

Covers every invariant in SCHEMA.md §9 and every locked invariant
in SEMANTICS.md §9. Tests are organized to mirror the spec sections.
"""

import unittest
from datetime import datetime, timezone, timedelta

from pact.scopes import (
    Scope, ScopeStore, DelegationValidator,
    RevocationResult, check_scope_validity,
)
from pact.types import Domain, FailureCode, OperationType, ScopeStatus


# ── Fixtures ──────────────────────────────────────────────────
# All time fixtures are relative to real wall-clock now so that
# pending/future comparisons work correctly against _now() in the engine.

def _now() -> datetime:
    return datetime.now(timezone.utc)

def ts(offset_seconds: int = 0) -> str:
    """ISO 8601 UTC timestamp offset from now."""
    t = _now() + timedelta(seconds=offset_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")

def dt(offset_seconds: int = 0) -> datetime:
    return _now() + timedelta(seconds=offset_seconds)


def make_scope(
    scope_id: str = "scope-001",
    parent_id: str | None = None,
    namespace: str = "calendar.events",
    types: list[str] = None,
    delegate: bool = False,
    revoke: str = "principal_only",
    status: ScopeStatus = ScopeStatus.ACTIVE,
    expires_at: str | None = None,
    effective_at: str | None = None,
    predicate: str = "TOP",
    ceiling: str = "TOP",
    issued_by: str = "principal:alice",
) -> Scope:
    return Scope(
        id=scope_id,
        issued_by_scope_id=parent_id,
        issued_by=issued_by,
        issued_at=ts(-3600),
        expires_at=expires_at,
        domain=Domain(
            namespace=namespace,
            types=tuple(OperationType(t) for t in (types or ["OBSERVE", "PROPOSE", "COMMIT"])),
        ),
        predicate=predicate,
        ceiling=ceiling,
        delegate=delegate,
        revoke=revoke,
        status=status,
        effective_at=effective_at,
    )


def root_scope(**kwargs) -> Scope:
    """A root scope (no parent)."""
    return make_scope(parent_id=None, **kwargs)


def child_scope(parent_id: str, scope_id: str = "scope-002", **kwargs) -> Scope:
    return make_scope(scope_id=scope_id, parent_id=parent_id, **kwargs)


# ═════════════════════════════════════════════════════════════
# §1: Operation Types and Contiguity
# ═════════════════════════════════════════════════════════════

class TestTypeContiguity(unittest.TestCase):
    """SCHEMA.md §1.2 — type-set rule."""

    def test_observe_only_valid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.OBSERVE,))
        self.assertTrue(r)

    def test_observe_propose_valid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.OBSERVE, OperationType.PROPOSE))
        self.assertTrue(r)

    def test_all_three_valid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT))
        self.assertTrue(r)

    def test_propose_only_invalid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.PROPOSE,))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_commit_only_invalid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.COMMIT,))
        self.assertFalse(r)

    def test_observe_commit_noncontiguous_invalid(self):
        r = DelegationValidator._validate_type_contiguity(
            (OperationType.OBSERVE, OperationType.COMMIT))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_empty_types_invalid(self):
        r = DelegationValidator._validate_type_contiguity(())
        self.assertFalse(r)

    def test_store_rejects_malformed_types_on_add(self):
        store = ScopeStore()
        s = make_scope(scope_id="bad", types=["PROPOSE"])
        with self.assertRaises(ValueError):
            store.add(s)


# ═════════════════════════════════════════════════════════════
# §2: Namespace Containment
# ═════════════════════════════════════════════════════════════

class TestNamespaceContainment(unittest.TestCase):
    """SCHEMA.md §2.2."""

    def _domain(self, ns: str) -> Domain:
        return Domain(namespace=ns, types=(OperationType.OBSERVE,))

    def test_equal_namespaces_contained(self):
        parent = root_scope(namespace="calendar.events")
        child = child_scope("scope-001", namespace="calendar.events")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertTrue(r)

    def test_child_sub_namespace_contained(self):
        parent = root_scope(namespace="calendar")
        child = child_scope("scope-001", namespace="calendar.events")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertTrue(r)

    def test_deep_child_namespace_contained(self):
        parent = root_scope(namespace="calendar")
        child = child_scope("scope-001", namespace="calendar.events.create")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertTrue(r)

    def test_sibling_namespace_not_contained(self):
        parent = root_scope(namespace="calendar.events")
        child = child_scope("scope-001", namespace="calendar.reminders")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_prefix_without_dot_not_contained(self):
        parent = root_scope(namespace="calendar")
        child = child_scope("scope-001", namespace="calendarX")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertFalse(r)

    def test_parent_wider_not_reversal(self):
        """Child cannot be wider than parent."""
        parent = root_scope(namespace="calendar.events")
        child = child_scope("scope-001", namespace="calendar")
        r = DelegationValidator._check_namespace_containment(parent, child)
        self.assertFalse(r)


# ═════════════════════════════════════════════════════════════
# §3: Type Containment at Delegation
# ═════════════════════════════════════════════════════════════

class TestTypeDelegation(unittest.TestCase):
    """SCHEMA.md §2, §7 — type escalation prevention."""

    def test_child_subset_types_allowed(self):
        parent = root_scope(types=["OBSERVE", "PROPOSE", "COMMIT"])
        child = child_scope("scope-001", types=["OBSERVE", "PROPOSE"])
        r = DelegationValidator._check_type_containment(parent, child)
        self.assertTrue(r)

    def test_child_equal_types_allowed(self):
        parent = root_scope(types=["OBSERVE", "PROPOSE"])
        child = child_scope("scope-001", types=["OBSERVE", "PROPOSE"])
        r = DelegationValidator._check_type_containment(parent, child)
        self.assertTrue(r)

    def test_type_escalation_denied(self):
        """Child claims COMMIT; parent only has OBSERVE+PROPOSE."""
        parent = root_scope(types=["OBSERVE", "PROPOSE"])
        child = child_scope("scope-001", types=["OBSERVE", "PROPOSE", "COMMIT"])
        r = DelegationValidator._check_type_containment(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.TYPE_ESCALATION)

    def test_type_escalation_single(self):
        parent = root_scope(types=["OBSERVE"])
        child = child_scope("scope-001", types=["OBSERVE", "PROPOSE"])
        r = DelegationValidator._check_type_containment(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.TYPE_ESCALATION)


# ═════════════════════════════════════════════════════════════
# §4: Delegate and Revoke Gates
# ═════════════════════════════════════════════════════════════

class TestOrthogonalGates(unittest.TestCase):
    """SCHEMA.md §1.3 — delegate and revoke are never implied."""

    def test_delegate_gate_parent_false_child_false_ok(self):
        parent = root_scope(delegate=False)
        child = child_scope("scope-001", delegate=False)
        r = DelegationValidator._check_delegate_gate(parent, child)
        self.assertTrue(r)

    def test_delegate_gate_parent_true_child_true_ok(self):
        parent = root_scope(delegate=True)
        child = child_scope("scope-001", delegate=True)
        r = DelegationValidator._check_delegate_gate(parent, child)
        self.assertTrue(r)

    def test_delegate_gate_parent_false_child_true_denied(self):
        """COMMIT does not imply delegate. Nothing implies delegate."""
        parent = root_scope(delegate=False, types=["OBSERVE", "PROPOSE", "COMMIT"])
        child = child_scope("scope-001", delegate=True)
        r = DelegationValidator._check_delegate_gate(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_UNAUTHORIZED)

    def test_revoke_gate_principal_only_to_principal_only_ok(self):
        parent = root_scope(revoke="principal_only")
        child = child_scope("scope-001", revoke="principal_only")
        r = DelegationValidator._check_revoke_gate(parent, child)
        self.assertTrue(r)

    def test_revoke_gate_coalition_granted_to_coalition_granted_ok(self):
        parent = root_scope(revoke="coalition_if_granted")
        child = child_scope("scope-001", revoke="coalition_if_granted")
        r = DelegationValidator._check_revoke_gate(parent, child)
        self.assertTrue(r)

    def test_revoke_gate_principal_only_cannot_grant_coalition(self):
        parent = root_scope(revoke="principal_only")
        child = child_scope("scope-001", revoke="coalition_if_granted")
        r = DelegationValidator._check_revoke_gate(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_UNAUTHORIZED)


# ═════════════════════════════════════════════════════════════
# §5: Ceiling Containment
# ═════════════════════════════════════════════════════════════

class TestCeilingContainment(unittest.TestCase):
    """SCHEMA.md §3, §7 — ceiling constraints."""

    def test_parent_top_allows_any_child_ceiling(self):
        parent = root_scope(ceiling="TOP")
        child = child_scope("scope-001", ceiling="action.cost <= 100")
        r = DelegationValidator._check_ceiling_containment(parent, child)
        self.assertTrue(r)

    def test_parent_top_allows_child_top(self):
        parent = root_scope(ceiling="TOP")
        child = child_scope("scope-001", ceiling="TOP")
        r = DelegationValidator._check_ceiling_containment(parent, child)
        self.assertTrue(r)

    def test_child_top_with_restricted_parent_denied(self):
        parent = root_scope(ceiling="action.cost <= 100")
        child = child_scope("scope-001", ceiling="TOP")
        r = DelegationValidator._check_ceiling_containment(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.CEILING_VIOLATED)

    def test_equal_ceilings_allowed(self):
        parent = root_scope(ceiling="action.cost <= 100")
        child = child_scope("scope-001", ceiling="action.cost <= 100")
        r = DelegationValidator._check_ceiling_containment(parent, child)
        self.assertTrue(r)

    def test_predicate_top_exceeds_restricted_ceiling(self):
        child = make_scope(predicate="TOP", ceiling="action.cost <= 100")
        r = DelegationValidator._check_predicate_within_ceiling(None, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_predicate_bottom_always_valid(self):
        child = make_scope(predicate="BOTTOM", ceiling="action.cost <= 100")
        r = DelegationValidator._check_predicate_within_ceiling(None, child)
        self.assertTrue(r)


# ═════════════════════════════════════════════════════════════
# §6: Parent Status Gate at Delegation
# ═════════════════════════════════════════════════════════════

class TestParentStatusGate(unittest.TestCase):
    """SCHEMA.md §7 status gate; SEMANTICS.md §5.2 — pending blocks delegation."""

    def test_active_parent_can_delegate(self):
        parent = root_scope(status=ScopeStatus.ACTIVE)
        child = child_scope("scope-001")
        r = DelegationValidator._check_parent_status(parent, child)
        self.assertTrue(r)

    def test_pending_revocation_blocks_delegation(self):
        """Invariant 7: pending_revocation blocks delegation."""
        parent = root_scope(
            status=ScopeStatus.PENDING_REVOCATION,
            effective_at=ts(+3600),
        )
        child = child_scope("scope-001")
        r = DelegationValidator._check_parent_status(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_revoked_parent_blocks_delegation(self):
        parent = root_scope(status=ScopeStatus.REVOKED)
        child = child_scope("scope-001")
        r = DelegationValidator._check_parent_status(parent, child)
        self.assertFalse(r)

    def test_expired_parent_blocks_delegation(self):
        parent = root_scope(status=ScopeStatus.EXPIRED)
        child = child_scope("scope-001")
        r = DelegationValidator._check_parent_status(parent, child)
        self.assertFalse(r)


# ═════════════════════════════════════════════════════════════
# §7: Full Delegation Validation
# ═════════════════════════════════════════════════════════════

class TestDelegationValidatorFull(unittest.TestCase):
    """DelegationValidator.validate() — all checks together."""

    def test_valid_delegation_allowed(self):
        parent = root_scope(
            scope_id="scope-001",
            namespace="calendar",
            types=["OBSERVE", "PROPOSE", "COMMIT"],
            delegate=True,
        )
        child = child_scope(
            "scope-001",
            scope_id="scope-002",
            namespace="calendar.events",
            types=["OBSERVE", "PROPOSE"],
            delegate=False,
        )
        r = DelegationValidator.validate(parent, child)
        self.assertTrue(r)

    def test_first_failure_wins(self):
        """Type escalation is checked; should not also report namespace error."""
        parent = root_scope(scope_id="scope-001", namespace="calendar.events",
                            types=["OBSERVE"])
        child = child_scope("scope-001", namespace="calendar.events",
                            types=["OBSERVE", "PROPOSE", "COMMIT"])
        r = DelegationValidator.validate(parent, child)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.TYPE_ESCALATION)


# ═════════════════════════════════════════════════════════════
# §8: ScopeStore — DAG Integrity
# ═════════════════════════════════════════════════════════════

class TestScopeStoreDAG(unittest.TestCase):
    """SCHEMA.md §4 — DAG integrity invariants."""

    def test_add_root_scope(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        self.assertIn("root", store)
        self.assertEqual(len(store), 1)

    def test_add_child_after_parent(self):
        store = ScopeStore()
        parent = root_scope(scope_id="root", delegate=True)
        child = child_scope("root", scope_id="child")
        store.add(parent)
        store.add(child)
        self.assertEqual(len(store), 2)

    def test_child_without_parent_raises(self):
        """Invariant 5: parent pointer must resolve."""
        store = ScopeStore()
        child = child_scope("nonexistent-parent")
        with self.assertRaises(ValueError, msg="Parent not found"):
            store.add(child)

    def test_duplicate_scope_id_raises(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        s2 = root_scope(scope_id="root")
        with self.assertRaises(ValueError, msg="Duplicate scope id"):
            store.add(s2)

    def test_depth_limit_enforced(self):
        """Compliance profile max_depth must be respected."""
        store = ScopeStore(max_depth=2)
        s0 = root_scope(scope_id="s0", delegate=True)
        s1 = child_scope("s0", scope_id="s1", delegate=True)
        s2 = child_scope("s1", scope_id="s2", delegate=True)
        s3 = child_scope("s2", scope_id="s3")
        store.add(s0)
        store.add(s1)
        store.add(s2)
        with self.assertRaises(ValueError, msg="Depth exceeded"):
            store.add(s3)

    def test_ancestors_of_root_empty(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        self.assertEqual(store.ancestors_of("root"), [])

    def test_ancestors_of_child(self):
        store = ScopeStore()
        s0 = root_scope(scope_id="s0", delegate=True)
        s1 = child_scope("s0", scope_id="s1", delegate=True)
        s2 = child_scope("s1", scope_id="s2")
        store.add(s0); store.add(s1); store.add(s2)
        ancestors = store.ancestors_of("s2")
        self.assertEqual([a.id for a in ancestors], ["s1", "s0"])

    def test_children_of(self):
        store = ScopeStore()
        s0 = root_scope(scope_id="s0", delegate=True)
        s1 = child_scope("s0", scope_id="s1")
        s2 = child_scope("s0", scope_id="s2")
        store.add(s0); store.add(s1); store.add(s2)
        children = store.children_of("s0")
        self.assertEqual({c.id for c in children}, {"s1", "s2"})

    def test_subtree_of_includes_all_descendants(self):
        store = ScopeStore()
        s0 = root_scope(scope_id="s0", delegate=True)
        s1 = child_scope("s0", scope_id="s1", delegate=True)
        s2 = child_scope("s1", scope_id="s2")
        s3 = child_scope("s0", scope_id="s3")
        store.add(s0); store.add(s1); store.add(s2); store.add(s3)
        subtree_ids = {s.id for s in store.subtree_of("s0")}
        self.assertEqual(subtree_ids, {"s0", "s1", "s2", "s3"})

    def test_subtree_of_leaf_is_just_self(self):
        store = ScopeStore()
        s0 = root_scope(scope_id="s0", delegate=True)
        s1 = child_scope("s0", scope_id="s1")
        store.add(s0); store.add(s1)
        subtree_ids = {s.id for s in store.subtree_of("s1")}
        self.assertEqual(subtree_ids, {"s1"})

    def test_descriptor_hash_set_on_add(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        self.assertIsNone(s.descriptor_hash)
        store.add(s)
        self.assertIsNotNone(s.descriptor_hash)
        self.assertEqual(len(s.descriptor_hash), 64)

    def test_descriptor_hash_deterministic(self):
        """Same scope descriptor must produce same hash."""
        s1 = root_scope(scope_id="root")
        s2 = root_scope(scope_id="root")
        self.assertEqual(s1.compute_hash(), s2.compute_hash())


# ═════════════════════════════════════════════════════════════
# §9: Validity Predicate — Single Scope
# ═════════════════════════════════════════════════════════════

class TestValidityPredicate(unittest.TestCase):
    """SCHEMA.md §5.2 conditions 1, 2, 4, 5 (condition 3 in TestAncestorRevocation)."""

    def test_active_scope_is_valid(self):
        s = root_scope(status=ScopeStatus.ACTIVE)
        r = check_scope_validity(s, at=dt(0))
        self.assertTrue(r)

    def test_revoked_scope_invalid(self):
        """Condition 2."""
        s = root_scope(status=ScopeStatus.REVOKED)
        r = check_scope_validity(s, at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_REVOKED)

    def test_expired_status_invalid(self):
        s = root_scope(status=ScopeStatus.EXPIRED)
        r = check_scope_validity(s, at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXPIRED)

    def test_expired_by_wall_clock(self):
        """Condition 5: expires_at in the past."""
        s = root_scope(expires_at=ts(-60))  # expired 1 minute ago
        r = check_scope_validity(s, at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXPIRED)

    def test_expires_at_in_future_valid(self):
        s = root_scope(expires_at=ts(+3600))  # expires in 1 hour
        r = check_scope_validity(s, at=dt(0))
        self.assertTrue(r)

    def test_pending_within_window_valid(self):
        """Condition 1b: pending but before effective_at."""
        s = root_scope(
            status=ScopeStatus.PENDING_REVOCATION,
            effective_at=ts(+3600),
        )
        r = check_scope_validity(s, at=dt(0))
        self.assertTrue(r)

    def test_pending_past_effective_invalid(self):
        """effective_at has passed — treated as revoked."""
        s = root_scope(
            status=ScopeStatus.PENDING_REVOCATION,
            effective_at=ts(-60),
        )
        r = check_scope_validity(s, at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_REVOKED)

    def test_pending_no_effective_at_fails_closed(self):
        """Malformed pending_revocation fails closed (SEMANTICS.md §7)."""
        s = root_scope(status=ScopeStatus.PENDING_REVOCATION, effective_at=None)
        r = check_scope_validity(s, at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_REVOKED)

    def test_contract_dissolved_fails(self):
        """Condition 4."""
        s = root_scope(status=ScopeStatus.ACTIVE)
        r = check_scope_validity(s, at=dt(0), contract_dissolved=True)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.CONTRACT_DISSOLVED)

    def test_contract_expired_fails(self):
        s = root_scope(status=ScopeStatus.ACTIVE)
        r = check_scope_validity(s, at=dt(0), contract_expired=True)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.CONTRACT_EXPIRED)


# ═════════════════════════════════════════════════════════════
# §10: Full Validity — Ancestor Traversal (Condition 3)
# ═════════════════════════════════════════════════════════════

class TestAncestorRevocation(unittest.TestCase):
    """
    SCHEMA.md §5.2 condition 3; SEMANTICS.md §4.1.
    Invariant 1: revoking a parent invalidates all descendants.
    """

    def _build_chain(self, depth: int = 3) -> tuple[ScopeStore, list[str]]:
        """Build a linear chain of scopes s0 → s1 → ... → s{depth-1}."""
        store = ScopeStore()
        ids = [f"s{i}" for i in range(depth)]
        store.add(root_scope(scope_id=ids[0], delegate=True))
        for i in range(1, depth):
            store.add(child_scope(ids[i-1], scope_id=ids[i], delegate=(i < depth-1)))
        return store, ids

    def test_valid_leaf_passes(self):
        store, ids = self._build_chain(3)
        r = store.validate_scope(ids[-1], at=dt(0))
        self.assertTrue(r)

    def test_unknown_scope_fails_closed(self):
        store = ScopeStore()
        r = store.validate_scope("nonexistent", at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_INVALID)

    def test_revoked_ancestor_invalidates_leaf(self):
        """Invariant 1 from SEMANTICS.md."""
        store, ids = self._build_chain(3)
        # Revoke the root
        store.revoke(ids[0])
        # Leaf should now be invalid
        r = store.validate_scope(ids[-1], at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_REVOKED)

    def test_revoked_middle_invalidates_leaf(self):
        store, ids = self._build_chain(4)
        store.revoke(ids[1])
        r = store.validate_scope(ids[-1], at=dt(0))
        self.assertFalse(r)

    def test_revoked_sibling_does_not_affect_other_branch(self):
        store = ScopeStore()
        root = root_scope(scope_id="root", delegate=True)
        left = child_scope("root", scope_id="left")
        right = child_scope("root", scope_id="right")
        store.add(root); store.add(left); store.add(right)
        store.revoke("left")
        # right branch should still be valid
        r = store.validate_scope("right", at=dt(0))
        self.assertTrue(r)
        # left is invalid
        r2 = store.validate_scope("left", at=dt(0))
        self.assertFalse(r2)

    def test_ancestor_expired_invalidates_descendant(self):
        store = ScopeStore()
        root = root_scope(scope_id="root", expires_at=ts(-60), delegate=True)
        child = child_scope("root", scope_id="child")
        store.add(root); store.add(child)
        root.status = ScopeStatus.EXPIRED  # simulate expiry processing
        r = store.validate_scope("child", at=dt(0))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.ANCESTOR_INVALID)


# ═════════════════════════════════════════════════════════════
# §11: Revocation Cascade
# ═════════════════════════════════════════════════════════════

class TestRevocationCascade(unittest.TestCase):
    """SEMANTICS.md §4.1 — cascading invalidation is the protocol default."""

    def _build_tree(self) -> tuple[ScopeStore, dict]:
        """
        Build a tree:
            root
            ├── a (delegate=True)
            │   ├── a1
            │   └── a2
            └── b
        """
        store = ScopeStore()
        scopes = {
            "root": root_scope(scope_id="root", delegate=True),
            "a":    child_scope("root", scope_id="a", delegate=True),
            "a1":   child_scope("a", scope_id="a1"),
            "a2":   child_scope("a", scope_id="a2"),
            "b":    child_scope("root", scope_id="b"),
        }
        for s in scopes.values():
            store.add(s)
        return store, scopes

    def test_revoke_root_cascades_to_all(self):
        store, scopes = self._build_tree()
        result = store.revoke("root")
        self.assertIsInstance(result, RevocationResult)
        revoked = set(result.revoked_ids)
        self.assertIn("root", revoked)
        self.assertIn("a", revoked)
        self.assertIn("a1", revoked)
        self.assertIn("a2", revoked)
        self.assertIn("b", revoked)
        self.assertEqual(len(revoked), 5)

    def test_revoke_subtree_only_affects_subtree(self):
        store, scopes = self._build_tree()
        result = store.revoke("a")
        revoked = set(result.revoked_ids)
        self.assertIn("a", revoked)
        self.assertIn("a1", revoked)
        self.assertIn("a2", revoked)
        self.assertNotIn("root", revoked)
        self.assertNotIn("b", revoked)

    def test_revoked_scopes_have_status_revoked(self):
        store, scopes = self._build_tree()
        store.revoke("a")
        self.assertEqual(scopes["a"].status, ScopeStatus.REVOKED)
        self.assertEqual(scopes["a1"].status, ScopeStatus.REVOKED)
        self.assertEqual(scopes["a2"].status, ScopeStatus.REVOKED)
        self.assertEqual(scopes["root"].status, ScopeStatus.ACTIVE)
        self.assertEqual(scopes["b"].status, ScopeStatus.ACTIVE)

    def test_revoke_leaf_only(self):
        store, scopes = self._build_tree()
        result = store.revoke("a1")
        self.assertEqual(result.revoked_ids, ["a1"])
        self.assertEqual(scopes["a"].status, ScopeStatus.ACTIVE)

    def test_revocation_result_properties(self):
        store, scopes = self._build_tree()
        result = store.revoke("a")
        self.assertTrue(result.is_immediate)
        self.assertFalse(result.is_pending)
        self.assertEqual(result.root_scope_id, "a")

    def test_double_revoke_is_idempotent(self):
        """Revoking an already-revoked scope should not raise."""
        store, scopes = self._build_tree()
        store.revoke("a1")
        result2 = store.revoke("a1")
        # Already revoked; result should have empty revoked_ids
        self.assertEqual(result2.revoked_ids, [])

    def test_revoke_updates_descriptor_hash(self):
        """Status change must produce a new descriptor_hash."""
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        hash_before = s.descriptor_hash
        store.revoke("root")
        hash_after = s.descriptor_hash
        self.assertNotEqual(hash_before, hash_after)


# ═════════════════════════════════════════════════════════════
# §12: Pending Revocation
# ═════════════════════════════════════════════════════════════

class TestPendingRevocation(unittest.TestCase):
    """SEMANTICS.md §5.1, §5.2 — future effective_at scheduling."""

    def test_future_effective_at_marks_pending(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        result = store.revoke("root", effective_at=dt(+3600))
        self.assertTrue(result.is_pending)
        self.assertFalse(result.is_immediate)
        self.assertEqual(s.status, ScopeStatus.PENDING_REVOCATION)

    def test_pending_scope_still_valid_before_effective_at(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        store.revoke("root", effective_at=dt(+3600))
        r = store.validate_scope("root", at=dt(0))
        self.assertTrue(r)

    def test_pending_scope_invalid_after_effective_at(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        store.revoke("root", effective_at=dt(+60))
        r = store.validate_scope("root", at=dt(+120))
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_REVOKED)

    def test_pending_scope_cannot_delegate(self):
        """Invariant 6: pending_revocation blocks delegation."""
        store = ScopeStore()
        parent = root_scope(scope_id="root", delegate=True)
        store.add(parent)
        store.revoke("root", effective_at=dt(+3600))
        child = child_scope("root", scope_id="child")
        r = DelegationValidator._check_parent_status(
            store.get("root"), child
        )
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.DELEGATION_MALFORMED)

    def test_apply_pending_promotes_to_revoked(self):
        store = ScopeStore()
        s = root_scope(scope_id="root", delegate=True)
        c = child_scope("root", scope_id="child")
        store.add(s); store.add(c)
        store.revoke("root", effective_at=dt(+60))
        # Before effective_at: still valid
        self.assertEqual(s.status, ScopeStatus.PENDING_REVOCATION)
        # Apply pending at a time after effective_at
        store.apply_pending_revocations(at=dt(+120))
        self.assertEqual(s.status, ScopeStatus.REVOKED)

    def test_immediate_revoke_is_default(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        result = store.revoke("root")   # no effective_at → immediate
        self.assertTrue(result.is_immediate)
        self.assertFalse(result.is_pending)
        self.assertEqual(s.status, ScopeStatus.REVOKED)


# ═════════════════════════════════════════════════════════════
# §13: Scope Serialization
# ═════════════════════════════════════════════════════════════

class TestScopeSerialization(unittest.TestCase):

    def test_round_trip(self):
        store = ScopeStore()
        s = root_scope(scope_id="root", expires_at=ts(+86400))
        store.add(s)
        d = s.to_dict()
        restored = Scope.from_dict(d)
        self.assertEqual(restored.id, s.id)
        self.assertEqual(restored.domain.namespace, s.domain.namespace)
        self.assertEqual(restored.descriptor_hash, s.descriptor_hash)
        self.assertEqual(restored.status, s.status)

    def test_hash_reproducible_after_round_trip(self):
        store = ScopeStore()
        s = root_scope(scope_id="root")
        store.add(s)
        d = s.to_dict()
        restored = Scope.from_dict(d)
        self.assertEqual(restored.compute_hash(), s.descriptor_hash)

    def test_is_root_true_for_root(self):
        s = root_scope(scope_id="root")
        self.assertTrue(s.is_root())

    def test_is_root_false_for_child(self):
        s = child_scope("parent", scope_id="child")
        self.assertFalse(s.is_root())


if __name__ == "__main__":
    unittest.main()
