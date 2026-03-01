"""
pact.validator — Unified enforcement boundary
spec: spec/scope/SCHEMA.md, spec/receipts/FAILURE_CODES.md

The single entry point for action authorization. Every action passes
through the 7-step enforcement pipeline. First failing step wins.

Enforcement order (locked):
  1. Contract valid (active, not expired, not dissolved)
  2. Scope exists and valid (not revoked, not expired, ancestors valid)
  3. Operation type authorized (action type in scope's domain types)
  4. Namespace containment (action namespace within scope namespace)
  5. Predicate evaluation (action satisfies scope predicate)
  6. Ceiling check (action within scope ceiling)
  7. Budget check (COMMIT only; consumed + requested ≤ ceiling)

Depends on: pact.interfaces, pact.types
Does NOT import any concrete store or evaluator classes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pact.interfaces import (
    BudgetLedgerProtocol,
    ConstraintEvaluatorProtocol,
    ContractStoreProtocol,
    ScopeStoreProtocol,
)
from pact.types import FailureCode, OperationType, UUID, ValidationResult


class Validator:
    """
    Unified action authorization validator.

    Composes the four protocol dependencies via constructor injection.
    The runtime wires concrete implementations; the validator sees
    only protocol surfaces.
    """

    def __init__(
        self,
        contracts: ContractStoreProtocol,
        scopes: ScopeStoreProtocol,
        constraints: ConstraintEvaluatorProtocol,
        budget: BudgetLedgerProtocol,
    ) -> None:
        self._contracts = contracts
        self._scopes = scopes
        self._constraints = constraints
        self._budget = budget

    def validate_action(
        self,
        action: dict[str, Any],
        scope_id: UUID,
        contract_id: UUID,
        *,
        at: datetime | None = None,
        budget_amounts: dict[str, str] | None = None,
    ) -> ValidationResult:
        """
        Authorize an action through the 7-step enforcement pipeline.

        action: dict with keys:
            type      — "OBSERVE" | "PROPOSE" | "COMMIT"
            namespace — hierarchical dotted path
            resource  — resource identifier
            params    — scalar parameters dict

        scope_id:       the scope authorizing this action
        contract_id:    the governing coalition contract
        at:             evaluation time (defaults to now)
        budget_amounts: optional {dimension: amount} for budget check (step 7)

        Returns ValidationResult.allow() or ValidationResult.deny(code, ...).
        """
        # ── Step 1: Contract validity ────────────────────────────
        result = self._check_contract(contract_id, at)

        if not result:
            contract_dissolved = (
                result.failure_code == FailureCode.CONTRACT_DISSOLVED
            )
            contract_expired = (
                result.failure_code == FailureCode.CONTRACT_EXPIRED
            )

            # Precedence §3.3: if contract is dissolved/expired, pass
            # flags to scope validation so it can emit CONTRACT_* as
            # primary code. For other contract failures (e.g. draft),
            # return the contract error immediately.
            if contract_dissolved or contract_expired:
                scope_result = self._scopes.validate_scope(
                    scope_id, at=at,
                    contract_dissolved=contract_dissolved,
                    contract_expired=contract_expired,
                )
                if not scope_result:
                    return scope_result
            # Contract is invalid — return contract error
            return result

        # ── Step 2: Scope existence and validity ─────────────────
        scope_result = self._check_scope(scope_id, at)
        if not scope_result:
            return scope_result

        # Fetch scope for remaining steps
        scope = self._scopes.get(scope_id)

        # ── Step 3: Operation type authorization ─────────────────
        result = self._check_type(action, scope)
        if not result:
            return result

        # ── Step 4: Namespace containment ────────────────────────
        result = self._check_namespace(action, scope)
        if not result:
            return result

        # ── Step 5: Predicate evaluation ─────────────────────────
        result = self._check_predicate(action, scope)
        if not result:
            return result

        # ── Step 6: Ceiling check ────────────────────────────────
        result = self._check_ceiling(action, scope)
        if not result:
            return result

        # ── Step 7: Budget check (COMMIT only) ───────────────────
        result = self._check_budget(action, scope_id, budget_amounts)
        if not result:
            return result

        return ValidationResult.allow()

    # ── Step implementations ─────────────────────────────────────

    def _check_contract(
        self, contract_id: UUID, at: datetime | None,
    ) -> ValidationResult:
        """Step 1: Contract existence and validity."""
        contract = self._contracts.get(contract_id)

        if contract is None:
            return ValidationResult.deny(
                FailureCode.CONTRACT_NOT_ACTIVE,
                f"Contract {contract_id!r} not found. Failing closed.",
                contract_id=contract_id,
            )

        if contract.is_valid(at):
            return ValidationResult.allow()

        # Determine specific failure code with precedence §3.2:
        # dissolution over expiry
        if contract.is_dissolved():
            return ValidationResult.deny(
                FailureCode.CONTRACT_DISSOLVED,
                "The governing Coalition Contract has been dissolved.",
                contract_id=contract_id,
            )

        if contract.is_expired_by_clock(at):
            return ValidationResult.deny(
                FailureCode.CONTRACT_EXPIRED,
                "The governing Coalition Contract has expired.",
                contract_id=contract_id,
            )

        # Draft or other non-active status
        return ValidationResult.deny(
            FailureCode.CONTRACT_NOT_ACTIVE,
            f"Contract {contract_id!r} is not active "
            f"(status: {contract.activation['status']!r}).",
            contract_id=contract_id,
            activation_status=contract.activation["status"],
        )

    def _check_scope(
        self, scope_id: UUID, at: datetime | None,
    ) -> ValidationResult:
        """Step 2: Scope existence and validity (including ancestor DAG)."""
        return self._scopes.validate_scope(scope_id, at=at)

    def _check_type(
        self, action: dict[str, Any], scope: Any,
    ) -> ValidationResult:
        """Step 3: Action type must be in scope's domain types."""
        try:
            action_type = OperationType(action["type"])
        except (KeyError, ValueError):
            return ValidationResult.deny(
                FailureCode.TYPE_ESCALATION,
                f"Unknown or missing action type: {action.get('type')!r}.",
            )

        if action_type not in scope.domain.types:
            return ValidationResult.deny(
                FailureCode.TYPE_ESCALATION,
                f"Action type {action_type.value!r} not authorized by scope. "
                f"Scope permits: {[t.value for t in scope.domain.types]}.",
                action_type=action_type.value,
                scope_types=[t.value for t in scope.domain.types],
            )

        return ValidationResult.allow()

    def _check_namespace(
        self, action: dict[str, Any], scope: Any,
    ) -> ValidationResult:
        """Step 4: Action namespace must be within scope namespace."""
        action_ns = action.get("namespace", "")

        if not scope.domain.contains_namespace(action_ns):
            return ValidationResult.deny(
                FailureCode.SCOPE_EXCEEDED,
                f"Action namespace {action_ns!r} is not within "
                f"scope namespace {scope.domain.namespace!r}.",
                action_namespace=action_ns,
                scope_namespace=scope.domain.namespace,
            )

        return ValidationResult.allow()

    def _check_predicate(
        self, action: dict[str, Any], scope: Any,
    ) -> ValidationResult:
        """Step 5: Action must satisfy scope predicate."""
        return self._constraints.evaluate(scope.predicate, action)

    def _check_ceiling(
        self, action: dict[str, Any], scope: Any,
    ) -> ValidationResult:
        """Step 6: Action must satisfy scope ceiling."""
        result = self._constraints.evaluate(scope.ceiling, action)

        if not result:
            # Override failure code: ceiling violations use CEILING_VIOLATED
            return ValidationResult.deny(
                FailureCode.CEILING_VIOLATED,
                result.message or "Action violates scope ceiling.",
                **result.detail,
            )

        return ValidationResult.allow()

    def _check_budget(
        self,
        action: dict[str, Any],
        scope_id: UUID,
        budget_amounts: dict[str, str] | None,
    ) -> ValidationResult:
        """Step 7: Budget availability (COMMIT actions only)."""
        if action.get("type") != OperationType.COMMIT.value:
            return ValidationResult.allow()

        if budget_amounts is None:
            return ValidationResult.allow()

        for dimension, amount in budget_amounts.items():
            result = self._budget.check_available(scope_id, dimension, amount)
            if not result:
                return result

        return ValidationResult.allow()
