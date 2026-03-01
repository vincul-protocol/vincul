"""
Tests for pact.runtime — Composition root integration tests
"""

import unittest

from pact.contract import CoalitionContract
from pact.runtime import PactRuntime
from pact.scopes import Scope
from pact.types import (
    ContractStatus, Domain, FailureCode, OperationType,
    ReceiptKind, ScopeStatus,
)


# ── Helpers ──────────────────────────────────────────────────────

CONTRACT_ID = "00000000-0000-0000-0000-c00000000001"
ROOT_SCOPE_ID = "00000000-0000-0000-0000-500000000001"
CHILD_SCOPE_ID = "00000000-0000-0000-0000-500000000002"


def _make_contract(status: str = "draft", expires_at: str | None = None) -> CoalitionContract:
    return CoalitionContract(
        contract_id=CONTRACT_ID,
        version="0.2",
        purpose={
            "title": "Group Trip Coalition",
            "description": "8 friends coordinating a trip",
            "expires_at": expires_at,
        },
        principals=[
            {"principal_id": "principal:alice", "role": "owner", "revoke_right": True},
            {"principal_id": "principal:bob", "role": "member", "revoke_right": False},
        ],
        governance={
            "decision_rule": "unanimous",
            "threshold": None,
            "signatory_policy": {},
        },
        budget_policy={"allowed": False, "dimensions": None, "per_principal_limit": None},
        activation={
            "status": status,
            "activated_at": "2025-01-01T00:00:00Z" if status != "draft" else None,
            "dissolved_at": None,
        },
    )


def _make_root_scope(
    types: tuple[OperationType, ...] = (
        OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT,
    ),
    namespace: str = "travel",
    predicate: str = "TOP",
    ceiling: str = "TOP",
) -> Scope:
    return Scope(
        id=ROOT_SCOPE_ID,
        issued_by_scope_id=None,
        issued_by="principal:alice",
        issued_at="2025-01-01T00:00:00Z",
        expires_at=None,
        domain=Domain(namespace=namespace, types=types),
        predicate=predicate,
        ceiling=ceiling,
        delegate=True,
        revoke="principal_only",
    )


def _make_child_scope(
    scope_id: str = CHILD_SCOPE_ID,
    parent_id: str = ROOT_SCOPE_ID,
    types: tuple[OperationType, ...] = (OperationType.OBSERVE, OperationType.PROPOSE),
    namespace: str = "travel.accommodation",
    predicate: str = "TOP",
    ceiling: str = "TOP",
    delegate: bool = False,
) -> Scope:
    return Scope(
        id=scope_id,
        issued_by_scope_id=parent_id,
        issued_by="principal:alice",
        issued_at="2025-01-01T00:01:00Z",
        expires_at=None,
        domain=Domain(namespace=namespace, types=types),
        predicate=predicate,
        ceiling=ceiling,
        delegate=delegate,
        revoke="principal_only",
    )


def _setup_active_runtime() -> PactRuntime:
    """Set up a runtime with an active contract and root scope."""
    rt = PactRuntime()
    rt.register_contract(_make_contract(status="draft"))
    rt.activate_contract(
        CONTRACT_ID,
        "2025-01-01T00:00:00Z",
        ["principal:alice", "principal:bob"],
    )
    rt.scopes.add(_make_root_scope())
    return rt


# ── TestRuntimeInit ──────────────────────────────────────────────

class TestRuntimeInit(unittest.TestCase):
    """Verify all stores are wired and validator is composed."""

    def test_stores_initialized(self):
        rt = PactRuntime()
        self.assertIsNotNone(rt.contracts)
        self.assertIsNotNone(rt.scopes)
        self.assertIsNotNone(rt.receipts)
        self.assertIsNotNone(rt.budget)
        self.assertIsNotNone(rt.validator)

    def test_custom_depth(self):
        rt = PactRuntime(max_delegation_depth=5)
        self.assertEqual(rt.scopes._max_depth, 5)


# ── TestRegisterContract ─────────────────────────────────────────

class TestRegisterContract(unittest.TestCase):

    def test_register_seals_and_stores(self):
        rt = PactRuntime()
        contract = _make_contract(status="draft")
        stored = rt.register_contract(contract)
        self.assertIsNotNone(stored.descriptor_hash)
        self.assertEqual(rt.contracts.get(CONTRACT_ID), stored)

    def test_register_duplicate_rejected(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        with self.assertRaises(ValueError):
            rt.register_contract(_make_contract(status="draft"))


# ── TestActivateContract ─────────────────────────────────────────

class TestActivateContract(unittest.TestCase):

    def test_activate_draft_to_active(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        before, after = rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        self.assertTrue(before.is_draft())
        self.assertTrue(after.is_active())

    def test_activate_governance_failure(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        with self.assertRaises(ValueError):
            rt.activate_contract(
                CONTRACT_ID,
                "2025-01-01T00:00:00Z",
                ["principal:alice"],  # unanimous requires both
            )

    def test_activate_returns_different_hashes(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        before, after = rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        self.assertNotEqual(before.descriptor_hash, after.descriptor_hash)


# ── TestDissolveContract ─────────────────────────────────────────

class TestDissolveContract(unittest.TestCase):

    def test_dissolve_emits_receipt(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        receipt = rt.dissolve_contract(
            CONTRACT_ID,
            "2025-01-02T00:00:00Z",
            "principal:alice",
            ["principal:alice", "principal:bob"],
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.CONTRACT_DISSOLUTION)
        self.assertIsNotNone(receipt.receipt_hash)

    def test_dissolve_receipt_in_log(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        receipt = rt.dissolve_contract(
            CONTRACT_ID,
            "2025-01-02T00:00:00Z",
            "principal:alice",
            ["principal:alice", "principal:bob"],
        )
        self.assertEqual(len(rt.receipts), 1)
        self.assertEqual(rt.receipts.get(receipt.receipt_hash), receipt)

    def test_dissolve_receipt_hashes(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        _, active = rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        active_hash = active.descriptor_hash
        receipt = rt.dissolve_contract(
            CONTRACT_ID,
            "2025-01-02T00:00:00Z",
            "principal:alice",
            ["principal:alice", "principal:bob"],
        )
        # Receipt should reference the pre-dissolution hash
        self.assertEqual(receipt.detail["contract_hash_before"], active_hash)
        self.assertNotEqual(receipt.detail["contract_hash_after"], active_hash)

    def test_dissolve_governance_failure(self):
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        with self.assertRaises(ValueError):
            rt.dissolve_contract(
                CONTRACT_ID,
                "2025-01-02T00:00:00Z",
                "principal:alice",
                ["principal:alice"],  # unanimous requires both
            )


# ── TestDelegate ─────────────────────────────────────────────────

class TestDelegate(unittest.TestCase):

    def test_valid_delegation(self):
        rt = _setup_active_runtime()
        child = _make_child_scope()
        receipt = rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        self.assertEqual(receipt.receipt_kind, ReceiptKind.DELEGATION)
        self.assertEqual(receipt.detail["child_scope_id"], CHILD_SCOPE_ID)
        self.assertEqual(receipt.detail["parent_scope_id"], ROOT_SCOPE_ID)

    def test_delegation_adds_to_scope_store(self):
        rt = _setup_active_runtime()
        child = _make_child_scope()
        rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        self.assertIsNotNone(rt.scopes.get(CHILD_SCOPE_ID))

    def test_delegation_receipt_in_log(self):
        rt = _setup_active_runtime()
        child = _make_child_scope()
        receipt = rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        self.assertEqual(len(rt.receipts), 1)
        self.assertEqual(rt.receipts.get(receipt.receipt_hash), receipt)

    def test_delegation_type_escalation_emits_failure(self):
        """Child requests COMMIT but parent only has OBSERVE."""
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        # Parent scope with OBSERVE only
        parent = _make_root_scope(types=(OperationType.OBSERVE,))
        rt.scopes.add(parent)

        # Child requests COMMIT — type escalation
        child = _make_child_scope(
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        )
        receipt = rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(receipt.detail["error_code"], FailureCode.TYPE_ESCALATION.value)

    def test_delegation_unauthorized_emits_failure(self):
        """Child claims delegate=True but parent has delegate=False."""
        rt = _setup_active_runtime()
        # Root has delegate=True, so let's make a child that tries to
        # grant delegate when parent doesn't have it — actually root
        # has delegate=True, so make a different scenario
        parent = Scope(
            id=ROOT_SCOPE_ID,
            issued_by_scope_id=None,
            issued_by="principal:alice",
            issued_at="2025-01-01T00:00:00Z",
            expires_at=None,
            domain=Domain(
                namespace="travel",
                types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
            ),
            predicate="TOP",
            ceiling="TOP",
            delegate=False,  # parent does NOT carry delegate
            revoke="principal_only",
        )
        rt2 = PactRuntime()
        rt2.register_contract(_make_contract(status="draft"))
        rt2.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        rt2.scopes.add(parent)

        child = _make_child_scope(delegate=True)  # child claims delegate
        receipt = rt2.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.DELEGATION_UNAUTHORIZED.value,
        )

    def test_delegation_failure_does_not_add_scope(self):
        """On delegation failure, the child scope is NOT added."""
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        parent = _make_root_scope(types=(OperationType.OBSERVE,))
        rt.scopes.add(parent)

        child = _make_child_scope(
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        )
        rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")
        # Child should NOT be in the store
        self.assertIsNone(rt.scopes.get(CHILD_SCOPE_ID))


# ── TestCommit ───────────────────────────────────────────────────

class TestCommit(unittest.TestCase):

    def test_valid_commit(self):
        rt = _setup_active_runtime()
        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {"duration_minutes": 60},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.COMMITMENT)
        self.assertEqual(receipt.detail["namespace"], "travel")
        self.assertEqual(receipt.detail["resource"], "hotel:001")

    def test_commit_receipt_in_log(self):
        rt = _setup_active_runtime()
        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(len(rt.receipts), 1)
        self.assertEqual(rt.receipts.get(receipt.receipt_hash), receipt)

    def test_commit_denied_emits_failure(self):
        """COMMIT on OBSERVE-only scope → TYPE_ESCALATION failure receipt."""
        rt = PactRuntime()
        rt.register_contract(_make_contract(status="draft"))
        rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        rt.scopes.add(_make_root_scope(types=(OperationType.OBSERVE,)))

        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.TYPE_ESCALATION.value,
        )

    def test_commit_with_budget(self):
        rt = _setup_active_runtime()
        rt.budget.set_ceiling(ROOT_SCOPE_ID, "GBP", "1500.00")

        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
            budget_amounts={"GBP": "200.00"},
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.COMMITMENT)
        self.assertEqual(receipt.detail["budget_consumed"], [
            {"dimension": "GBP", "amount": "200.00"},
        ])

    def test_commit_records_budget_delta(self):
        rt = _setup_active_runtime()
        rt.budget.set_ceiling(ROOT_SCOPE_ID, "GBP", "1500.00")

        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
            budget_amounts={"GBP": "200.00"},
        )
        from decimal import Decimal
        self.assertEqual(
            rt.budget.get_balance(ROOT_SCOPE_ID, "GBP"),
            Decimal("1300.00"),
        )

    def test_commit_budget_exceeded_emits_failure(self):
        rt = _setup_active_runtime()
        rt.budget.set_ceiling(ROOT_SCOPE_ID, "GBP", "100.00")

        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
            budget_amounts={"GBP": "200.00"},
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.BUDGET_EXCEEDED.value,
        )

    def test_commit_budget_not_recorded_on_failure(self):
        """Budget delta should NOT be recorded when validation fails."""
        rt = _setup_active_runtime()
        rt.budget.set_ceiling(ROOT_SCOPE_ID, "GBP", "100.00")

        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
            budget_amounts={"GBP": "200.00"},
        )
        from decimal import Decimal
        # Balance should still be 100 — no delta recorded
        self.assertEqual(
            rt.budget.get_balance(ROOT_SCOPE_ID, "GBP"),
            Decimal("100.00"),
        )

    def test_commit_reversible_fields(self):
        rt = _setup_active_runtime()
        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "hotel:001",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
            reversible=True,
            revert_window="PT10M",
            external_ref="ext:booking:abc123",
        )
        self.assertTrue(receipt.detail["reversible"])
        self.assertEqual(receipt.detail["revert_window"], "PT10M")
        self.assertEqual(receipt.detail["external_ref"], "ext:booking:abc123")


# ── TestRevoke ───────────────────────────────────────────────────

class TestRevoke(unittest.TestCase):

    def test_revoke_emits_receipt(self):
        rt = _setup_active_runtime()
        receipt, rev_result = rt.revoke(
            ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.REVOCATION)
        self.assertIsNotNone(receipt.receipt_hash)

    def test_revoke_cascades(self):
        rt = _setup_active_runtime()
        child = _make_child_scope()
        rt.delegate(ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice")

        receipt, rev_result = rt.revoke(
            ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertIn(ROOT_SCOPE_ID, rev_result.revoked_ids)
        self.assertIn(CHILD_SCOPE_ID, rev_result.revoked_ids)

    def test_revoke_scope_hash_captured_before_mutation(self):
        """GOTCHA 1: Receipt must carry the pre-mutation scope hash."""
        rt = _setup_active_runtime()
        scope_before = rt.scopes.get(ROOT_SCOPE_ID)
        hash_before = scope_before.descriptor_hash

        receipt, _ = rt.revoke(
            ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        # Receipt should carry the pre-mutation hash
        self.assertEqual(receipt.scope_hash, hash_before)
        # Scope hash should have changed after revocation
        scope_after = rt.scopes.get(ROOT_SCOPE_ID)
        self.assertNotEqual(scope_after.descriptor_hash, hash_before)

    def test_revoke_receipt_in_log(self):
        rt = _setup_active_runtime()
        receipt, _ = rt.revoke(
            ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        # delegation receipt was already in log from setup? No, _setup_active_runtime
        # adds scope directly to store, not through delegate()
        self.assertEqual(len(rt.receipts), 1)
        self.assertEqual(rt.receipts.get(receipt.receipt_hash), receipt)


# ── TestEndToEnd ─────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """Full lifecycle: register → activate → delegate → commit → revoke → dissolve."""

    def test_full_lifecycle(self):
        rt = PactRuntime()

        # 1. Register and activate contract
        rt.register_contract(_make_contract(status="draft"))
        before, after = rt.activate_contract(
            CONTRACT_ID,
            "2025-01-01T00:00:00Z",
            ["principal:alice", "principal:bob"],
        )
        self.assertTrue(after.is_active())

        # 2. Add root scope and delegate child
        rt.scopes.add(_make_root_scope())
        child = _make_child_scope()
        delegation_r = rt.delegate(
            ROOT_SCOPE_ID, child, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(delegation_r.receipt_kind, ReceiptKind.DELEGATION)

        # 3. Commit an action on the child scope
        action = {
            "type": "OBSERVE",
            "namespace": "travel.accommodation",
            "resource": "hotel:001",
            "params": {},
        }
        commit_r = rt.commit(
            action, CHILD_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(commit_r.receipt_kind, ReceiptKind.COMMITMENT)

        # 4. Revoke the root scope (cascades to child)
        revoke_r, rev_result = rt.revoke(
            ROOT_SCOPE_ID, CONTRACT_ID, "principal:alice",
        )
        self.assertEqual(revoke_r.receipt_kind, ReceiptKind.REVOCATION)
        self.assertEqual(len(rev_result.revoked_ids), 2)

        # 5. Dissolve the contract
        dissolve_r = rt.dissolve_contract(
            CONTRACT_ID,
            "2025-01-02T00:00:00Z",
            "principal:alice",
            ["principal:alice", "principal:bob"],
        )
        self.assertEqual(dissolve_r.receipt_kind, ReceiptKind.CONTRACT_DISSOLUTION)

        # Verify receipt log has all 4 receipts
        self.assertEqual(len(rt.receipts), 4)
        timeline = rt.receipts.timeline()
        kinds = [r.receipt_kind for r in timeline]
        self.assertEqual(kinds, [
            ReceiptKind.DELEGATION,
            ReceiptKind.COMMITMENT,
            ReceiptKind.REVOCATION,
            ReceiptKind.CONTRACT_DISSOLUTION,
        ])


# ── TestDemoScenario ─────────────────────────────────────────────

class TestDemoScenario(unittest.TestCase):
    """
    Demo: 8 friends trip. Yaki has OBSERVE+PROPOSE on travel.accommodation.
    Yaki attempts COMMIT → TYPE_ESCALATION failure receipt.
    """

    def _setup_demo(self) -> PactRuntime:
        rt = PactRuntime()

        # Contract with 2 principals (simplified from 8 for test brevity)
        contract = CoalitionContract(
            contract_id=CONTRACT_ID,
            version="0.2",
            purpose={
                "title": "Group Trip to Portugal",
                "description": "8 friends planning a trip",
                "expires_at": None,
            },
            principals=[
                {"principal_id": "principal:maya", "role": "owner", "revoke_right": True},
                {"principal_id": "principal:yaki", "role": "member", "revoke_right": False},
            ],
            governance={
                "decision_rule": "unanimous",
                "threshold": None,
                "signatory_policy": {},
            },
            budget_policy={
                "allowed": True,
                "dimensions": [{"name": "EUR", "unit": "currency", "precision": 2}],
                "per_principal_limit": None,
            },
            activation={
                "status": "draft",
                "activated_at": None,
                "dissolved_at": None,
            },
        )
        rt.register_contract(contract)
        rt.activate_contract(
            CONTRACT_ID,
            "2025-06-01T00:00:00Z",
            ["principal:maya", "principal:yaki"],
        )

        # Root scope: full authority over travel domain
        root = Scope(
            id=ROOT_SCOPE_ID,
            issued_by_scope_id=None,
            issued_by="principal:maya",
            issued_at="2025-06-01T00:00:00Z",
            expires_at=None,
            domain=Domain(
                namespace="travel",
                types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
            ),
            predicate="TOP",
            ceiling="TOP",
            delegate=True,
            revoke="principal_only",
        )
        rt.scopes.add(root)

        # Yaki's scope: OBSERVE+PROPOSE only on accommodation
        yaki_scope = Scope(
            id=CHILD_SCOPE_ID,
            issued_by_scope_id=ROOT_SCOPE_ID,
            issued_by="principal:maya",
            issued_at="2025-06-01T00:01:00Z",
            expires_at=None,
            domain=Domain(
                namespace="travel.accommodation",
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
            ),
            predicate="action.params.price_per_night <= 200",
            ceiling="action.params.price_per_night <= 500",
            delegate=False,
            revoke="principal_only",
        )
        rt.delegate(ROOT_SCOPE_ID, yaki_scope, CONTRACT_ID, "principal:maya")

        # Set budget ceiling
        rt.budget.set_ceiling(ROOT_SCOPE_ID, "EUR", "1500.00")

        return rt

    def test_yaki_observe_allowed(self):
        rt = self._setup_demo()
        action = {
            "type": "OBSERVE",
            "namespace": "travel.accommodation",
            "resource": "hotel:sunset-palace",
            "params": {"price_per_night": 150},
        }
        receipt = rt.commit(
            action, CHILD_SCOPE_ID, CONTRACT_ID, "principal:yaki",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.COMMITMENT)

    def test_yaki_propose_allowed(self):
        rt = self._setup_demo()
        action = {
            "type": "PROPOSE",
            "namespace": "travel.accommodation",
            "resource": "hotel:sunset-palace",
            "params": {"price_per_night": 100},
        }
        receipt = rt.commit(
            action, CHILD_SCOPE_ID, CONTRACT_ID, "principal:yaki",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.COMMITMENT)

    def test_yaki_commit_denied_type_escalation(self):
        rt = self._setup_demo()
        action = {
            "type": "COMMIT",
            "namespace": "travel.accommodation",
            "resource": "hotel:sunset-palace",
            "params": {"price_per_night": 150},
        }
        receipt = rt.commit(
            action, CHILD_SCOPE_ID, CONTRACT_ID, "principal:yaki",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.TYPE_ESCALATION.value,
        )

    def test_yaki_predicate_violation(self):
        """Yaki tries to OBSERVE a hotel costing 300/night — predicate says ≤ 200."""
        rt = self._setup_demo()
        action = {
            "type": "OBSERVE",
            "namespace": "travel.accommodation",
            "resource": "hotel:grand-palace",
            "params": {"price_per_night": 300},
        }
        receipt = rt.commit(
            action, CHILD_SCOPE_ID, CONTRACT_ID, "principal:yaki",
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.SCOPE_EXCEEDED.value,
        )

    def test_maya_commit_allowed_on_root(self):
        """Maya has full COMMIT authority on the root scope."""
        rt = self._setup_demo()
        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "flight:lisbon",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:maya",
            budget_amounts={"EUR": "500.00"},
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.COMMITMENT)

    def test_budget_tracking_across_commits(self):
        """Multiple commits accumulate budget consumption."""
        rt = self._setup_demo()
        from decimal import Decimal

        for i in range(3):
            action = {
                "type": "COMMIT",
                "namespace": "travel",
                "resource": f"expense:{i}",
                "params": {},
            }
            rt.commit(
                action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:maya",
                budget_amounts={"EUR": "400.00"},
            )

        self.assertEqual(
            rt.budget.get_balance(ROOT_SCOPE_ID, "EUR"),
            Decimal("300.00"),
        )

    def test_budget_exceeded_after_spending(self):
        """After spending 1200 EUR, a 400 EUR commit is denied."""
        rt = self._setup_demo()

        # Spend 1200 across 3 commits
        for i in range(3):
            action = {
                "type": "COMMIT",
                "namespace": "travel",
                "resource": f"expense:{i}",
                "params": {},
            }
            rt.commit(
                action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:maya",
                budget_amounts={"EUR": "400.00"},
            )

        # This one pushes over the limit
        action = {
            "type": "COMMIT",
            "namespace": "travel",
            "resource": "expense:final",
            "params": {},
        }
        receipt = rt.commit(
            action, ROOT_SCOPE_ID, CONTRACT_ID, "principal:maya",
            budget_amounts={"EUR": "400.00"},
        )
        self.assertEqual(receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(
            receipt.detail["error_code"],
            FailureCode.BUDGET_EXCEEDED.value,
        )


if __name__ == "__main__":
    unittest.main()
