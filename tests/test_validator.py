"""
Tests for pact.validator — Unified enforcement boundary

Tests compose concrete stores and pass them through the Validator,
exercising the full 7-step enforcement pipeline.
"""

import unittest
from datetime import datetime, timezone

from pact.budget import BudgetLedger
from pact.constraints import ConstraintEvaluator
from pact.contract import CoalitionContract, ContractStore
from pact.scopes import Scope, ScopeStore
from pact.types import (
    ContractStatus, Domain, FailureCode, OperationType, ScopeStatus,
)
from pact.validator import Validator


# ── Helpers ──────────────────────────────────────────────────────

CONTRACT_ID = "00000000-0000-0000-0000-c00000000001"
ROOT_SCOPE_ID = "00000000-0000-0000-0000-500000000001"
CHILD_SCOPE_ID = "00000000-0000-0000-0000-500000000002"


def _make_contract(
    status: str = "active",
    expires_at: str | None = None,
    dissolved_at: str | None = None,
) -> CoalitionContract:
    return CoalitionContract(
        contract_id=CONTRACT_ID,
        version="0.2",
        purpose={
            "title": "Test Coalition",
            "description": "For validator tests",
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
            "dissolved_at": dissolved_at,
        },
    )


def _make_scope(
    scope_id: str = ROOT_SCOPE_ID,
    parent_id: str | None = None,
    types: tuple[OperationType, ...] = (OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
    namespace: str = "travel",
    predicate: str = "TOP",
    ceiling: str = "TOP",
    status: ScopeStatus = ScopeStatus.ACTIVE,
    expires_at: str | None = None,
) -> Scope:
    return Scope(
        id=scope_id,
        issued_by_scope_id=parent_id,
        issued_by="principal:alice",
        issued_at="2025-01-01T00:00:00Z",
        expires_at=expires_at,
        domain=Domain(namespace=namespace, types=types),
        predicate=predicate,
        ceiling=ceiling,
        delegate=True,
        revoke="principal_only",
        status=status,
    )


def _make_action(
    action_type: str = "OBSERVE",
    namespace: str = "travel",
    resource: str = "hotel:001",
    params: dict | None = None,
) -> dict:
    return {
        "type": action_type,
        "namespace": namespace,
        "resource": resource,
        "params": params or {},
    }


def _build_validator(
    contract: CoalitionContract | None = None,
    scopes: list[Scope] | None = None,
    budget_ceilings: dict[tuple[str, str], str] | None = None,
) -> Validator:
    """Build a Validator with the given fixtures wired up."""
    cs = ContractStore()
    if contract is not None:
        cs.put(contract)

    ss = ScopeStore()
    for s in (scopes or []):
        ss.add(s)

    ce = ConstraintEvaluator()
    bl = BudgetLedger()
    if budget_ceilings:
        for (sid, dim), ceiling in budget_ceilings.items():
            bl.set_ceiling(sid, dim, ceiling)

    return Validator(contracts=cs, scopes=ss, constraints=ce, budget=bl)


# ── Step 1: Contract validity ────────────────────────────────────

class TestStep1ContractValidity(unittest.TestCase):
    """Step 1: Contract must be active, not expired, not dissolved."""

    def test_active_contract_allows(self):
        v = _build_validator(
            contract=_make_contract(status="active"),
            scopes=[_make_scope()],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertTrue(result)

    def test_missing_contract_denies(self):
        v = _build_validator(scopes=[_make_scope()])
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, "nonexistent-id")
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_NOT_ACTIVE)

    def test_draft_contract_denies(self):
        v = _build_validator(
            contract=_make_contract(status="draft"),
            scopes=[_make_scope()],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_NOT_ACTIVE)

    def test_dissolved_contract_denies(self):
        v = _build_validator(
            contract=_make_contract(status="dissolved", dissolved_at="2025-01-01T01:00:00Z"),
            scopes=[_make_scope()],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_DISSOLVED)

    def test_expired_contract_denies(self):
        v = _build_validator(
            contract=_make_contract(status="active", expires_at="2025-01-01T00:30:00Z"),
            scopes=[_make_scope()],
        )
        at = datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
        result = v.validate_action(
            _make_action(), ROOT_SCOPE_ID, CONTRACT_ID, at=at,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_EXPIRED)

    def test_dissolved_and_expired_emits_dissolved(self):
        """Precedence §3.2: dissolution over expiry."""
        v = _build_validator(
            contract=_make_contract(
                status="dissolved",
                expires_at="2025-01-01T00:30:00Z",
                dissolved_at="2025-01-01T01:00:00Z",
            ),
            scopes=[_make_scope()],
        )
        at = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc)
        result = v.validate_action(
            _make_action(), ROOT_SCOPE_ID, CONTRACT_ID, at=at,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_DISSOLVED)


# ── Step 2: Scope validity ───────────────────────────────────────

class TestStep2ScopeValidity(unittest.TestCase):
    """Step 2: Scope must exist and pass the full validity predicate."""

    def test_active_scope_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertTrue(result)

    def test_missing_scope_denies(self):
        v = _build_validator(contract=_make_contract())
        result = v.validate_action(_make_action(), "nonexistent-scope", CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_INVALID)

    def test_revoked_scope_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(status=ScopeStatus.REVOKED)],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_REVOKED)

    def test_expired_scope_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(expires_at="2025-01-01T00:30:00Z")],
        )
        at = datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
        result = v.validate_action(
            _make_action(), ROOT_SCOPE_ID, CONTRACT_ID, at=at,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXPIRED)

    def test_ancestor_revoked_denies(self):
        root = _make_scope(scope_id=ROOT_SCOPE_ID, status=ScopeStatus.REVOKED)
        child = _make_scope(scope_id=CHILD_SCOPE_ID, parent_id=ROOT_SCOPE_ID)
        v = _build_validator(
            contract=_make_contract(),
            scopes=[root, child],
        )
        result = v.validate_action(_make_action(), CHILD_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.ANCESTOR_INVALID)

    def test_contract_dissolved_takes_precedence_over_scope(self):
        """Precedence §3.3: CONTRACT_* over SCOPE_*."""
        v = _build_validator(
            contract=_make_contract(status="dissolved", dissolved_at="2025-01-01T01:00:00Z"),
            scopes=[_make_scope(status=ScopeStatus.REVOKED)],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        # Contract failure is primary per §3.3
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_DISSOLVED)


# ── Step 3: Operation type authorization ─────────────────────────

class TestStep3TypeAuthorization(unittest.TestCase):
    """Step 3: Action type must be in scope's domain types."""

    def test_observe_on_full_scope_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
        )
        result = v.validate_action(
            _make_action(action_type="OBSERVE"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_commit_on_observe_only_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(types=(OperationType.OBSERVE,))],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.TYPE_ESCALATION)

    def test_propose_on_observe_propose_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(types=(OperationType.OBSERVE, OperationType.PROPOSE))],
        )
        result = v.validate_action(
            _make_action(action_type="PROPOSE"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_commit_on_observe_propose_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(types=(OperationType.OBSERVE, OperationType.PROPOSE))],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.TYPE_ESCALATION)

    def test_unknown_type_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
        )
        result = v.validate_action(
            _make_action(action_type="DELETE"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.TYPE_ESCALATION)


# ── Step 4: Namespace containment ────────────────────────────────

class TestStep4NamespaceContainment(unittest.TestCase):
    """Step 4: Action namespace must be within scope namespace."""

    def test_exact_namespace_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel")],
        )
        result = v.validate_action(
            _make_action(namespace="travel"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_child_namespace_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel")],
        )
        result = v.validate_action(
            _make_action(namespace="travel.accommodation"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_deeply_nested_namespace_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel")],
        )
        result = v.validate_action(
            _make_action(namespace="travel.accommodation.hotels.luxury"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_unrelated_namespace_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel")],
        )
        result = v.validate_action(
            _make_action(namespace="finance"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_prefix_collision_denies(self):
        """'travelogue' is not within 'travel'."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel")],
        )
        result = v.validate_action(
            _make_action(namespace="travelogue"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)


# ── Step 5: Predicate evaluation ─────────────────────────────────

class TestStep5PredicateEvaluation(unittest.TestCase):
    """Step 5: Action must satisfy scope predicate."""

    def test_top_predicate_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(predicate="TOP")],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertTrue(result)

    def test_bottom_predicate_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(predicate="BOTTOM")],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_atom_satisfied_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(predicate="action.params.duration_minutes <= 60")],
        )
        result = v.validate_action(
            _make_action(params={"duration_minutes": 30}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_atom_violated_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(predicate="action.params.duration_minutes <= 60")],
        )
        result = v.validate_action(
            _make_action(params={"duration_minutes": 90}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_conjunction_all_pass_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                predicate="action.params.duration_minutes <= 60 AND action.params.cost <= 100"
            )],
        )
        result = v.validate_action(
            _make_action(params={"duration_minutes": 30, "cost": 50}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_conjunction_one_fails_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                predicate="action.params.duration_minutes <= 60 AND action.params.cost <= 100"
            )],
        )
        result = v.validate_action(
            _make_action(params={"duration_minutes": 30, "cost": 200}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)


# ── Step 6: Ceiling check ────────────────────────────────────────

class TestStep6CeilingCheck(unittest.TestCase):
    """Step 6: Action must satisfy scope ceiling."""

    def test_top_ceiling_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(ceiling="TOP")],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertTrue(result)

    def test_ceiling_satisfied_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(ceiling="action.params.cost <= 500")],
        )
        result = v.validate_action(
            _make_action(params={"cost": 100}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_ceiling_violated_denies_with_ceiling_violated_code(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(ceiling="action.params.cost <= 500")],
        )
        result = v.validate_action(
            _make_action(params={"cost": 1000}),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CEILING_VIOLATED)

    def test_bottom_ceiling_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(ceiling="BOTTOM")],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CEILING_VIOLATED)


# ── Step 7: Budget check ─────────────────────────────────────────

class TestStep7BudgetCheck(unittest.TestCase):
    """Step 7: Budget availability (COMMIT only)."""

    def test_no_budget_amounts_skips(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_non_commit_skips_budget(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
            budget_ceilings={(ROOT_SCOPE_ID, "GBP"): "100.00"},
        )
        result = v.validate_action(
            _make_action(action_type="OBSERVE"), ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "50.00"},
        )
        self.assertTrue(result)

    def test_within_budget_allows(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
            budget_ceilings={(ROOT_SCOPE_ID, "GBP"): "100.00"},
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "50.00"},
        )
        self.assertTrue(result)

    def test_exceeds_budget_denies(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
            budget_ceilings={(ROOT_SCOPE_ID, "GBP"): "100.00"},
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "200.00"},
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.BUDGET_EXCEEDED)

    def test_multiple_dimensions_first_failure_wins(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
            budget_ceilings={
                (ROOT_SCOPE_ID, "GBP"): "100.00",
                (ROOT_SCOPE_ID, "api_calls"): "10",
            },
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "50.00", "api_calls": "20"},
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.BUDGET_EXCEEDED)

    def test_no_ceiling_registered_allows(self):
        """Budget check with no ceiling registered → allow (untracked dimension)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope()],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "999.99"},
        )
        self.assertTrue(result)


# ── Enforcement order ────────────────────────────────────────────

class TestEnforcementOrder(unittest.TestCase):
    """Verify that steps execute in order and first failure wins."""

    def test_contract_fails_before_scope(self):
        """Contract failure (step 1) takes priority over missing scope (step 2)."""
        v = _build_validator(
            contract=_make_contract(status="draft"),
        )
        result = v.validate_action(
            _make_action(), "nonexistent-scope", CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CONTRACT_NOT_ACTIVE)

    def test_scope_fails_before_type(self):
        """Scope failure (step 2) takes priority over type escalation (step 3)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                types=(OperationType.OBSERVE,),
                status=ScopeStatus.REVOKED,
            )],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_REVOKED)

    def test_type_fails_before_namespace(self):
        """Type escalation (step 3) takes priority over namespace (step 4)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                types=(OperationType.OBSERVE,),
                namespace="travel",
            )],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT", namespace="finance"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.TYPE_ESCALATION)

    def test_namespace_fails_before_predicate(self):
        """Namespace violation (step 4) takes priority over predicate (step 5)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(namespace="travel", predicate="BOTTOM")],
        )
        result = v.validate_action(
            _make_action(namespace="finance"), ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)
        # Verify it's namespace, not predicate — check the message
        self.assertIn("namespace", result.message)

    def test_predicate_fails_before_ceiling(self):
        """Predicate failure (step 5) takes priority over ceiling (step 6)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(predicate="BOTTOM", ceiling="BOTTOM")],
        )
        result = v.validate_action(_make_action(), ROOT_SCOPE_ID, CONTRACT_ID)
        self.assertFalse(result)
        # Predicate returns SCOPE_EXCEEDED, ceiling would return CEILING_VIOLATED
        self.assertEqual(result.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_ceiling_fails_before_budget(self):
        """Ceiling failure (step 6) takes priority over budget (step 7)."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(ceiling="action.params.cost <= 50")],
            budget_ceilings={(ROOT_SCOPE_ID, "GBP"): "10.00"},
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT", params={"cost": 100}),
            ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "200.00"},
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.CEILING_VIOLATED)


# ── Demo scenario ────────────────────────────────────────────────

class TestDemoScenario(unittest.TestCase):
    """
    The spec demo: Yaki attempts COMMIT on travel.accommodation
    but her scope only has types=[OBSERVE, PROPOSE].
    Expected: TYPE_ESCALATION.
    """

    def test_yaki_commit_denied(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
                namespace="travel.accommodation",
            )],
        )
        result = v.validate_action(
            _make_action(action_type="COMMIT", namespace="travel.accommodation"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.TYPE_ESCALATION)
        self.assertIn("COMMIT", result.message)

    def test_yaki_observe_allowed(self):
        """Same scope, but OBSERVE is permitted."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
                namespace="travel.accommodation",
            )],
        )
        result = v.validate_action(
            _make_action(action_type="OBSERVE", namespace="travel.accommodation"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)

    def test_yaki_propose_allowed(self):
        """Same scope, PROPOSE is also permitted."""
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
                namespace="travel.accommodation",
            )],
        )
        result = v.validate_action(
            _make_action(action_type="PROPOSE", namespace="travel.accommodation"),
            ROOT_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)


# ── Full pipeline pass ───────────────────────────────────────────

class TestFullPipelinePass(unittest.TestCase):
    """Verify that a fully valid action passes all 7 steps."""

    def test_all_steps_pass(self):
        v = _build_validator(
            contract=_make_contract(),
            scopes=[_make_scope(
                predicate="action.params.duration_minutes <= 60",
                ceiling="action.params.duration_minutes <= 120",
            )],
            budget_ceilings={(ROOT_SCOPE_ID, "GBP"): "1500.00"},
        )
        result = v.validate_action(
            _make_action(
                action_type="COMMIT",
                namespace="travel",
                params={"duration_minutes": 30},
            ),
            ROOT_SCOPE_ID, CONTRACT_ID,
            budget_amounts={"GBP": "200.00"},
        )
        self.assertTrue(result)

    def test_all_steps_pass_child_scope(self):
        root = _make_scope(scope_id=ROOT_SCOPE_ID, namespace="travel")
        child = _make_scope(
            scope_id=CHILD_SCOPE_ID,
            parent_id=ROOT_SCOPE_ID,
            namespace="travel.accommodation",
            types=(OperationType.OBSERVE, OperationType.PROPOSE),
        )
        v = _build_validator(
            contract=_make_contract(),
            scopes=[root, child],
        )
        result = v.validate_action(
            _make_action(action_type="OBSERVE", namespace="travel.accommodation"),
            CHILD_SCOPE_ID, CONTRACT_ID,
        )
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
