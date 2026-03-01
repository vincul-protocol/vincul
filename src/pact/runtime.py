"""
pact.runtime — Composition root
spec: spec/implementation/GOTCHAS.md

The only module that imports concrete classes from siblings.
Wires all stores, evaluators, and the validator into a single
PactRuntime that exposes high-level orchestration methods.

Each operation follows the two-store model:
  validate → mutate state → emit receipt

Depends on: every other pact module (composition root)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pact.budget import BudgetLedger
from pact.constraints import ConstraintEvaluator
from pact.contract import CoalitionContract, ContractStore
from pact.hashing import pact_hash_constraint
from pact.receipts import (
    Receipt, ReceiptLog,
    commitment_receipt, delegation_receipt, dissolution_receipt,
    failure_receipt, revocation_receipt,
)
from pact.scopes import DelegationValidator, RevocationResult, Scope, ScopeStore
from pact.types import FailureCode, ReceiptKind, Timestamp, UUID
from pact.validator import Validator


# Keys that failure_receipt takes as explicit parameters — must not
# appear in **extra_detail to avoid duplicate keyword argument errors.
_FAILURE_RECEIPT_KEYS = frozenset({
    "initiated_by", "scope_id", "scope_hash", "contract_id",
    "contract_hash", "error_code", "message", "recoverable",
    "prior_receipt",
})


def _extra_detail(result_detail: dict) -> dict:
    """Filter out keys that collide with failure_receipt's explicit params."""
    return {k: v for k, v in result_detail.items() if k not in _FAILURE_RECEIPT_KEYS}


class PactRuntime:
    """
    Composition root for the Pact Protocol.

    Instantiates and wires all concrete stores, evaluators, and the
    validator. Exposes high-level operations that follow the two-store
    model: validate → mutate → emit receipt.
    """

    def __init__(self, max_delegation_depth: int = 10) -> None:
        self.contracts = ContractStore()
        self.scopes = ScopeStore(max_depth=max_delegation_depth)
        self.receipts = ReceiptLog()
        self.budget = BudgetLedger()
        self._evaluator = ConstraintEvaluator()
        self.validator = Validator(
            contracts=self.contracts,
            scopes=self.scopes,
            constraints=self._evaluator,
            budget=self.budget,
        )

    # ── Contract lifecycle ───────────────────────────────────────

    def register_contract(
        self, contract: CoalitionContract,
    ) -> CoalitionContract:
        """
        Register a contract. Validates structure, seals, and indexes.
        No receipt emitted (pre-activation).
        """
        return self.contracts.put(contract)

    def activate_contract(
        self,
        contract_id: UUID,
        activated_at: Timestamp,
        signatures: list[str],
    ) -> tuple[CoalitionContract, CoalitionContract]:
        """
        Transition draft → active.

        Returns (before, after). Raises ValueError on governance
        failure or invalid transition.
        """
        return self.contracts.activate(contract_id, activated_at, signatures)

    def dissolve_contract(
        self,
        contract_id: UUID,
        dissolved_at: Timestamp,
        dissolved_by: str,
        signatures: list[str],
    ) -> Receipt:
        """
        Transition active → dissolved. Emits dissolution receipt.

        Raises ValueError on governance failure or invalid transition.
        Returns the dissolution receipt.
        """
        before, after = self.contracts.dissolve(
            contract_id, dissolved_at, dissolved_by, signatures,
        )

        r = dissolution_receipt(
            initiated_by=dissolved_by,
            contract_id=contract_id,
            contract_hash_before=before.descriptor_hash,
            contract_hash_after=after.descriptor_hash,
            dissolved_at=dissolved_at,
            decision_rule=before.governance["decision_rule"],
            signatures_present=len(signatures),
            signatories=sorted(signatures),
        )
        self.receipts.append(r)
        return r

    # ── Delegation ───────────────────────────────────────────────

    def delegate(
        self,
        parent_scope_id: UUID,
        child: Scope,
        contract_id: UUID,
        initiated_by: str,
    ) -> Receipt:
        """
        Create a child scope delegated from parent.

        Validates delegation constraints (DelegationValidator),
        adds child to scope store, and emits a delegation receipt.
        On validation failure, emits a failure receipt instead.
        """
        parent = self.scopes.get_or_raise(parent_scope_id)
        contract = self.contracts.get_or_raise(contract_id)

        # Validate delegation constraints
        result = DelegationValidator.validate(parent, child)

        if not result:
            r = failure_receipt(
                initiated_by=initiated_by,
                scope_id=parent_scope_id,
                scope_hash=parent.descriptor_hash,
                contract_id=contract_id,
                contract_hash=contract.descriptor_hash,
                error_code=result.failure_code,
                message=result.message,
                **_extra_detail(result.detail),
            )
            self.receipts.append(r)
            return r

        # Add child to scope store (validates structure, seals)
        child = self.scopes.add(child)

        r = delegation_receipt(
            initiated_by=initiated_by,
            scope_id=parent_scope_id,
            scope_hash=parent.descriptor_hash,
            contract_id=contract_id,
            contract_hash=contract.descriptor_hash,
            child_scope_id=child.id,
            child_scope_hash=child.descriptor_hash,
            parent_scope_id=parent_scope_id,
            types_granted=[t.value for t in child.domain.types],
            delegate_granted=child.delegate,
            revoke_granted=child.revoke,
            expires_at=child.expires_at,
            ceiling_hash=pact_hash_constraint(child.ceiling),
        )
        self.receipts.append(r)
        return r

    # ── Commit ───────────────────────────────────────────────────

    def commit(
        self,
        action: dict[str, Any],
        scope_id: UUID,
        contract_id: UUID,
        initiated_by: str,
        *,
        reversible: bool = False,
        revert_window: str | None = None,
        external_ref: str | None = None,
        budget_amounts: dict[str, str] | None = None,
    ) -> Receipt:
        """
        Execute a COMMIT action through the full enforcement pipeline.

        On validation failure, emits a failure receipt.
        On success, records budget deltas and emits a commitment receipt.
        """
        # Validate through the 7-step pipeline
        result = self.validator.validate_action(
            action, scope_id, contract_id,
            budget_amounts=budget_amounts,
        )

        if not result:
            scope = self.scopes.get(scope_id)
            contract = self.contracts.get(contract_id)
            r = failure_receipt(
                initiated_by=initiated_by,
                scope_id=scope_id,
                scope_hash=scope.descriptor_hash if scope else None,
                contract_id=contract_id,
                contract_hash=contract.descriptor_hash if contract else None,
                error_code=result.failure_code,
                message=result.message,
                **_extra_detail(result.detail),
            )
            self.receipts.append(r)
            return r

        # Record budget deltas
        if budget_amounts:
            for dimension, amount in budget_amounts.items():
                self.budget.record_delta(scope_id, dimension, amount)

        # Emit commitment receipt
        scope = self.scopes.get(scope_id)
        contract = self.contracts.get(contract_id)

        budget_consumed = None
        if budget_amounts:
            budget_consumed = [
                {"dimension": dim, "amount": amt}
                for dim, amt in budget_amounts.items()
            ]

        r = commitment_receipt(
            initiated_by=initiated_by,
            scope_id=scope_id,
            scope_hash=scope.descriptor_hash,
            contract_id=contract_id,
            contract_hash=contract.descriptor_hash,
            namespace=action["namespace"],
            resource=action.get("resource", ""),
            params=action.get("params", {}),
            reversible=reversible,
            revert_window=revert_window,
            external_ref=external_ref,
            budget_consumed=budget_consumed,
        )
        self.receipts.append(r)
        return r

    # ── Revocation ───────────────────────────────────────────────

    def revoke(
        self,
        scope_id: UUID,
        contract_id: UUID,
        initiated_by: str,
        authority_type: str = "principal",
        *,
        effective_at: datetime | None = None,
    ) -> tuple[Receipt, RevocationResult]:
        """
        Revoke a scope and cascade to all descendants.

        GOTCHA 1: Captures scope hash BEFORE mutation.
        Returns (receipt, RevocationResult).
        """
        scope = self.scopes.get_or_raise(scope_id)
        contract = self.contracts.get_or_raise(contract_id)

        # Capture hash before mutation (GOTCHA 1)
        scope_hash_before = scope.descriptor_hash

        # Execute revocation cascade
        rev_result = self.scopes.revoke(
            scope_id,
            effective_at=effective_at,
            initiated_by=initiated_by,
        )

        r = revocation_receipt(
            initiated_by=initiated_by,
            scope_id=scope_id,
            scope_hash=scope_hash_before,
            contract_id=contract_id,
            contract_hash=contract.descriptor_hash,
            revocation_root=scope_id,
            authority_type=authority_type,
            effective_at=rev_result.effective_at,
        )
        self.receipts.append(r)
        return r, rev_result
