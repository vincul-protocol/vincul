"""
pact.budget — Budget ledger: parallel state for budget tracking
spec: spec/budget/LEDGER.md

The ledger is the authoritative source for running totals per scope
per dimension. Receipts declare deltas but never reconstruct totals
(invariant 1).

Implements BudgetLedgerProtocol from pact.interfaces.

Depends on: pact.hashing, pact.types
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pact.hashing import normalize_ledger_balances
from pact.types import FailureCode, UUID, ValidationResult


class BudgetLedger:
    """
    In-memory budget ledger tracking per-scope, per-dimension consumption.

    Ceilings are set externally (by the runtime when scopes are created).
    Consumption is recorded via record_delta(). The validator calls
    check_available() at enforcement step 7.

    Satisfies BudgetLedgerProtocol from pact.interfaces.
    """

    def __init__(self) -> None:
        self._ceilings: dict[tuple[UUID, str], Decimal] = {}
        self._consumed: dict[tuple[UUID, str], Decimal] = {}
        self._commitment_refs: dict[tuple[UUID, str], list[str]] = {}

    # ── Ceiling management ───────────────────────────────────────

    def set_ceiling(
        self, scope_id: UUID, dimension: str, ceiling: str,
    ) -> None:
        """
        Register the spending ceiling for a scope+dimension pair.

        ceiling: a decimal string (e.g. "100.00").
        Raises ValueError if ceiling is not a valid non-negative decimal.
        """
        try:
            value = Decimal(ceiling)
        except InvalidOperation:
            raise ValueError(f"Invalid ceiling value: {ceiling!r}")

        if value < 0:
            raise ValueError(
                f"Ceiling must be non-negative, got {ceiling!r}"
            )

        key = (scope_id, dimension)
        self._ceilings[key] = value
        # Initialize consumed to zero if not already tracked
        if key not in self._consumed:
            self._consumed[key] = Decimal("0")
            self._commitment_refs[key] = []

    # ── Delta recording ──────────────────────────────────────────

    def record_delta(
        self,
        scope_id: UUID,
        dimension: str,
        delta: str,
        receipt_hash: str | None = None,
    ) -> None:
        """
        Record a budget consumption delta.

        delta: a decimal string, must be non-negative (invariant 2).
        receipt_hash: optional receipt reference for snapshot tracking.
        Raises ValueError if delta is negative or not a valid decimal.
        """
        try:
            amount = Decimal(delta)
        except InvalidOperation:
            raise ValueError(f"Invalid delta value: {delta!r}")

        if amount < 0:
            raise ValueError(
                f"Budget delta must be non-negative, got {delta!r}"
            )

        key = (scope_id, dimension)
        self._consumed[key] = self._consumed.get(key, Decimal("0")) + amount

        if receipt_hash is not None:
            self._commitment_refs.setdefault(key, []).append(receipt_hash)

    # ── Balance queries ──────────────────────────────────────────

    def get_balance(self, scope_id: UUID, dimension: str) -> Decimal | None:
        """
        Remaining budget for a scope+dimension.

        Returns ceiling - consumed, or None if no ceiling is registered.
        """
        key = (scope_id, dimension)
        ceiling = self._ceilings.get(key)
        if ceiling is None:
            return None
        consumed = self._consumed.get(key, Decimal("0"))
        return ceiling - consumed

    # ── Availability check (validator step 7) ────────────────────

    def check_available(
        self, scope_id: UUID, dimension: str, amount: str,
    ) -> ValidationResult:
        """
        Check if amount is available within the ceiling.

        Returns allow() if:
          - No ceiling registered (budget not tracked for this dimension)
          - consumed + amount <= ceiling
        Returns deny(BUDGET_EXCEEDED) if consumed + amount > ceiling.
        """
        key = (scope_id, dimension)
        ceiling = self._ceilings.get(key)

        # No ceiling → budget not tracked → allow
        if ceiling is None:
            return ValidationResult.allow()

        try:
            requested = Decimal(amount)
        except InvalidOperation:
            return ValidationResult.deny(
                FailureCode.BUDGET_EXCEEDED,
                f"Invalid budget amount: {amount!r}",
                scope_id=scope_id,
                dimension=dimension,
            )

        consumed = self._consumed.get(key, Decimal("0"))
        remaining = ceiling - consumed

        if consumed + requested > ceiling:
            return ValidationResult.deny(
                FailureCode.BUDGET_EXCEEDED,
                f"Budget exceeded for dimension {dimension!r}: "
                f"requested {amount}, remaining {str(remaining)}",
                scope_id=scope_id,
                dimension=dimension,
                ceiling=str(ceiling),
                consumed=str(consumed),
                requested=amount,
                remaining=str(remaining),
            )

        return ValidationResult.allow()

    # ── Snapshot generation ──────────────────────────────────────

    def snapshot(
        self,
        scope_id: UUID,
        snapshot_type: str,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Produce a ledger snapshot dict for the given scope.

        snapshot_type: one of "periodic", "revocation", "dissolution", "on_demand".
        Balances are normalized (sorted by dimension) per HASHING.md §7.5.

        Returns a dict matching the CI vector schema for ledger_snapshot detail.
        """
        # Collect all dimensions for this scope
        balances_raw: list[dict] = []
        all_refs: list[str] = []

        for (sid, dim), ceiling in self._ceilings.items():
            if sid != scope_id:
                continue
            consumed = self._consumed.get((sid, dim), Decimal("0"))
            remaining = ceiling - consumed
            refs = self._commitment_refs.get((sid, dim), [])

            balances_raw.append({
                "dimension": dim,
                "ceiling": float(ceiling),
                "consumed": float(consumed),
                "remaining": float(remaining),
                "commitment_count": len(refs),
            })
            all_refs.extend(refs)

        balances = normalize_ledger_balances(balances_raw)

        return {
            "snapshot_type": snapshot_type,
            "covers_scope_id": scope_id,
            "snapshot_period": {
                "from": period_from,
                "to": period_to,
            },
            "balances": balances,
            "prior_snapshot": None,
            "commitment_refs": sorted(set(all_refs)),
        }

    # ── Metrics ──────────────────────────────────────────────────

    def dimensions_for(self, scope_id: UUID) -> list[str]:
        """Return sorted list of dimensions with ceilings for a scope."""
        return sorted(
            dim for (sid, dim) in self._ceilings if sid == scope_id
        )
