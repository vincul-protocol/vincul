"""
pact.interfaces — Protocol definitions for all store and evaluator boundaries

This module is the dependency firewall. Every module in pact depends downward
on pact.types and pact.interfaces. No module imports concrete classes from
a sibling module — only the runtime composition root does that.

Import graph:
    pact.types       ← pure data, no deps
    pact.interfaces  ← depends only on pact.types
    pact.contract    ← implements ContractStoreProtocol
    pact.scopes      ← implements ScopeStoreProtocol
    pact.receipts    ← implements ReceiptLogProtocol
    pact.constraints ← implements ConstraintEvaluatorProtocol
    pact.budget      ← implements BudgetLedgerProtocol
    pact.validator   ← depends on interfaces only
    pact.runtime     ← composition root; wires concrete → interfaces
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pact.types import Hash, Timestamp, UUID, ValidationResult


# ── Contract Store ───────────────────────────────────────────

@runtime_checkable
class ContractStoreProtocol(Protocol):
    """
    Source of truth for coalition contract state.

    Lifecycle mutations (activate, dissolve) return (before, after) tuples
    so the caller can build receipts with both hashes. Receipt emission is
    the caller's responsibility — the store is deterministic state only.
    """

    def put(self, contract: Any) -> Any:
        """Store a contract. Returns the stored contract."""
        ...

    def get(self, contract_id: UUID) -> Any:
        """Retrieve by contract_id. Returns CoalitionContract | None."""
        ...

    def get_by_hash(self, contract_hash: Hash) -> Any:
        """Retrieve by descriptor_hash. Returns CoalitionContract | None."""
        ...

    def activate(
        self,
        contract_id: UUID,
        activated_at: Timestamp,
        signatures: list[str],
    ) -> Any:
        """
        Transition draft → active. Returns (contract_before, contract_after).
        Raises on invalid transition or insufficient signatures.
        """
        ...

    def dissolve(
        self,
        contract_id: UUID,
        dissolved_at: Timestamp,
        dissolved_by: str,
        signatures: list[str],
    ) -> Any:
        """
        Transition active → dissolved. Returns (contract_before, contract_after).
        Raises on invalid transition or insufficient signatures per governance rule.
        """
        ...

    def is_active(self, contract_id: UUID) -> bool:
        """True if contract exists and activation.status == 'active'."""
        ...

    def is_dissolved(self, contract_id: UUID) -> bool:
        """True if contract exists and activation.status == 'dissolved'."""
        ...


# ── Scope Store ──────────────────────────────────────────────

@runtime_checkable
class ScopeStoreProtocol(Protocol):
    """
    Scope DAG store. Source of truth for scope state, delegation
    structure, and revocation cascade.
    """

    def add(self, scope: Any) -> Any:
        """Add a scope to the DAG. Returns the scope (sealed)."""
        ...

    def get(self, scope_id: UUID) -> Any:
        """Retrieve by scope_id. Returns Scope | None."""
        ...

    def validate_scope(self, scope_id: UUID, **kwargs: Any) -> ValidationResult:
        """Full validity predicate including ancestor traversal."""
        ...

    def revoke(self, scope_id: UUID, **kwargs: Any) -> Any:
        """Revoke a scope and cascade. Returns RevocationResult."""
        ...

    def ancestors_of(self, scope_id: UUID) -> list[Any]:
        """All ancestors from parent to root, in order."""
        ...

    def subtree_of(self, scope_id: UUID) -> list[Any]:
        """All descendants including self. BFS order."""
        ...


# ── Receipt Log ──────────────────────────────────────────────

@runtime_checkable
class ReceiptLogProtocol(Protocol):
    """
    Append-only audit trail. Source of truth for the event narrative.
    Receipts reference contract/scope hashes but never reconstruct state.
    """

    def append(self, receipt: Any) -> Any:
        """Append a sealed receipt. Raises on missing hash or tamper."""
        ...

    def get(self, receipt_hash: Hash) -> Any:
        """Retrieve by receipt_hash. Returns Receipt | None."""
        ...

    def for_contract(self, contract_id: UUID) -> list[Any]:
        """All receipts for a contract, in append order."""
        ...

    def for_scope(self, scope_id: UUID) -> list[Any]:
        """All receipts for a scope, in append order."""
        ...

    def timeline(self) -> list[Any]:
        """All receipts in append order."""
        ...


# ── Constraint Evaluator ────────────────────────────────────

@runtime_checkable
class ConstraintEvaluatorProtocol(Protocol):
    """
    Evaluates a ConstraintExpression against an action dict.

    v0.2 grammar: TOP | BOTTOM | And(atom, atom, ...)
    Atom: field_path op literal  (<=, >=, <, >, ==, !=)
    """

    def evaluate(self, expression: str, action: dict[str, Any]) -> ValidationResult:
        """
        Evaluate expression against action.
        Returns ValidationResult.allow() or ValidationResult.deny(SCOPE_EXCEEDED, ...).
        """
        ...


# ── Budget Ledger ────────────────────────────────────────────

@runtime_checkable
class BudgetLedgerProtocol(Protocol):
    """
    Parallel state for budget tracking. Receipts reference deltas;
    the ledger is the authoritative running total.

    pact.validator step 7 (BUDGET_EXCEEDED) calls check_available().
    """

    def record_delta(self, scope_id: UUID, dimension: str, delta: str) -> None:
        """Record a budget consumption delta. delta is a decimal string."""
        ...

    def get_balance(self, scope_id: UUID, dimension: str) -> Any:
        """Current balance for a dimension. Returns Decimal | None."""
        ...

    def check_available(
        self, scope_id: UUID, dimension: str, amount: str,
    ) -> ValidationResult:
        """
        Check if amount is available within ceiling.
        Returns allow() or deny(BUDGET_EXCEEDED, ...).
        """
        ...

    def snapshot(self, scope_id: UUID, snapshot_type: str) -> Any:
        """Produce a LedgerSnapshot for the given scope. Returns snapshot dict."""
        ...
