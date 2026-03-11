"""vincul.sdk.context — VinculContext: one-stop coalition setup.

Handles principal registration, contract creation/activation, and
scope chain construction in a few calls. Wraps VinculRuntime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from vincul.contract import CoalitionContract
from vincul.identity import KeyPair, PrincipalRegistry
from vincul.receipts import Receipt, activation_receipt, new_uuid, now_utc
from vincul.runtime import VinculRuntime
from vincul.scopes import Scope
from vincul.types import Domain, OperationType


_ALL_OPS = (OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT)


class VinculContext:
    """One-stop setup for a vincul coalition.

    Usage::

        ctx = VinculContext()
        key_a = ctx.add_principal("vendor:A", role="agent_host", permissions=["delegate", "commit"])
        key_b = ctx.add_principal("vendor:B", role="tool_provider", permissions=["delegate", "commit", "revoke"])

        contract = ctx.create_contract(purpose_title="My marketplace")

        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP", "ttl_hours": 2},
                {"ceiling": "params.quantity <= 10", "ttl_hours": 1.5},
                {"ceiling": "params.quantity <= 5", "delegate": False, "ttl_hours": 1},
            ],
        )
    """

    def __init__(self, max_delegation_depth: int = 10) -> None:
        self.runtime = VinculRuntime(max_delegation_depth=max_delegation_depth)
        self.registry = PrincipalRegistry()
        self._keypairs: dict[str, KeyPair] = {}
        self._principals: list[dict[str, Any]] = []

    # ── Principals ────────────────────────────────────────────

    def add_principal(
        self,
        principal_id: str,
        *,
        role: str,
        permissions: list[str],
    ) -> KeyPair:
        """Register a principal with a fresh Ed25519 keypair."""
        key = KeyPair.generate(principal_id)
        self.registry.register_keypair(key)
        self._keypairs[principal_id] = key
        self._principals.append({
            "principal_id": principal_id,
            "role": role,
            "permissions": permissions,
        })
        return key

    def keypair(self, principal_id: str) -> KeyPair:
        """Retrieve a previously registered keypair."""
        return self._keypairs[principal_id]

    # ── Contract ──────────────────────────────────────────────

    def create_contract(
        self,
        *,
        purpose_title: str,
        purpose_description: str = "",
        expires_at: str = "2026-12-31T00:00:00Z",
        governance_rule: str = "unanimous",
        governance: dict[str, Any] | None = None,
        budget_allowed: bool = False,
        budget_dimensions: list[dict] | None = None,
        signatories: list[str] | None = None,
    ) -> CoalitionContract:
        """Create, register, and activate a coalition contract.

        Uses all registered principals. Governance defaults to unanimous.
        Pass ``governance`` dict to override the default governance structure.
        Returns the activated contract.
        """
        gov = governance or {
            "decision_rule": governance_rule,
            "threshold": None,
        }
        contract = CoalitionContract(
            contract_id=new_uuid(),
            version="0.2",
            purpose={
                "title": purpose_title,
                "description": purpose_description,
                "expires_at": expires_at,
            },
            principals=list(self._principals),
            governance=gov,
            budget_policy={
                "allowed": budget_allowed,
                "dimensions": budget_dimensions,
            },
            activation={"status": "draft"},
        )

        contract = self.runtime.register_contract(contract)

        sigs = signatories or [p["principal_id"] for p in self._principals]
        activated_at = now_utc()
        self.runtime.activate_contract(
            contract.contract_id,
            activated_at=activated_at,
            signatures=sigs,
        )

        # Emit activation receipt
        receipt = activation_receipt(
            initiated_by=sigs[0],
            contract_id=contract.contract_id,
            contract_hash=contract.descriptor_hash,
            activated_at=activated_at,
            decision_rule=contract.governance.get("decision_rule", "unanimous"),
            signatures_present=len(sigs),
            signatories=sigs,
        )
        self.runtime.receipts.append(receipt)

        return contract

    # ── Scope chain ───────────────────────────────────────────

    def create_scope_chain(
        self,
        *,
        contract_id: str,
        issued_by: str,
        namespace: str,
        operations: tuple[OperationType, ...] | None = None,
        chain: list[dict[str, Any]],
    ) -> list[Scope]:
        """Build a scope chain (root -> ... -> leaf) from a simple config.

        Each entry in ``chain`` is a dict with optional keys:
          - ceiling (str): constraint expression, default "TOP"
          - predicate (str): constraint expression, default = ceiling
          - delegate (bool): default True for all except last
          - ttl_hours (float): time-to-live, default decreasing from 2h
          - revoke (str): default "principal_only"

        Returns the list of created Scope objects in chain order.
        """
        ops = operations or _ALL_OPS
        now = datetime.now(timezone.utc)
        scopes: list[Scope] = []
        parent_id: str | None = None

        for i, level in enumerate(chain):
            ceiling = level.get("ceiling", "TOP")
            predicate = level.get("predicate", ceiling)
            delegate = level.get("delegate", i < len(chain) - 1)
            ttl_hours = level.get("ttl_hours", max(0.5, 2.0 - i * 0.5))
            revoke = level.get("revoke", "principal_only")

            scope = Scope(
                id=new_uuid(),
                issued_by_scope_id=parent_id,
                issued_by=issued_by,
                issued_at=now_utc(),
                expires_at=(now + timedelta(hours=ttl_hours)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                domain=Domain(namespace=namespace, types=tuple(ops)),
                predicate=predicate,
                ceiling=ceiling,
                delegate=delegate,
                revoke=revoke,
            )

            if parent_id is None:
                scope = self.runtime.scopes.add(scope)
            else:
                self.runtime.delegate(
                    parent_scope_id=parent_id,
                    child=scope,
                    contract_id=contract_id,
                    initiated_by=issued_by,
                )
                scope = self.runtime.scopes.get(scope.id)

            scopes.append(scope)
            parent_id = scope.id

        return scopes

    # ── Scope management ─────────────────────────────────────

    def add_scope(self, scope: Scope) -> Scope:
        """Add a root scope (no parent) to the scope store."""
        return self.runtime.scopes.add(scope)

    def delegate_scope(
        self,
        *,
        parent_scope_id: str,
        child: Scope,
        contract_id: str,
        initiated_by: str,
    ):
        """Delegate a child scope from parent. Returns (receipt, child_scope)."""
        receipt = self.runtime.delegate(
            parent_scope_id=parent_scope_id,
            child=child,
            contract_id=contract_id,
            initiated_by=initiated_by,
        )
        child_scope = self.runtime.scopes.get(child.id)
        return receipt, child_scope

    # ── Budget ─────────────────────────────────────────────────

    def set_budget_ceiling(self, scope_id: str, dimension: str, amount: str) -> None:
        """Set a budget ceiling for a scope dimension."""
        self.runtime.budget.set_ceiling(scope_id, dimension, amount)

    # ── Dissolution ────────────────────────────────────────────

    def dissolve_contract(
        self,
        *,
        contract_id: str,
        dissolved_by: str,
        signatures: list[str],
        dissolved_at: str | None = None,
    ):
        """Dissolve a contract. Returns the dissolution receipt."""
        return self.runtime.dissolve_contract(
            contract_id=contract_id,
            dissolved_at=dissolved_at or now_utc(),
            dissolved_by=dissolved_by,
            signatures=signatures,
        )

    # ── Revocation ─────────────────────────────────────────────

    def revoke_scope(
        self,
        scope_id: str,
        contract_id: str,
        initiated_by: str,
        authority_type: str = "principal",
    ):
        """Revoke a scope with BFS cascade. Returns (receipt, RevocationResult)."""
        return self.runtime.revoke(
            scope_id=scope_id,
            contract_id=contract_id,
            initiated_by=initiated_by,
            authority_type=authority_type,
        )

    # ── Commit ──────────────────────────────────────────────────

    def commit(
        self,
        *,
        action: dict[str, Any],
        scope_id: str,
        contract_id: str,
        initiated_by: str,
        reversible: bool = False,
        revert_window: str | None = None,
        external_ref: str | None = None,
        budget_amounts: dict[str, str] | None = None,
    ) -> Receipt:
        """Execute an action through the full 7-step enforcement pipeline.

        Returns a commitment receipt on success, failure receipt on denial.
        """
        return self.runtime.commit(
            action=action,
            scope_id=scope_id,
            contract_id=contract_id,
            initiated_by=initiated_by,
            reversible=reversible,
            revert_window=revert_window,
            external_ref=external_ref,
            budget_amounts=budget_amounts,
        )

    # ── Lookups ────────────────────────────────────────────────

    def get_scope(self, scope_id: str) -> Scope | None:
        """Look up a scope by ID. Returns None if not found."""
        return self.runtime.scopes.get(scope_id)

    def get_contract(self, contract_id: str) -> CoalitionContract | None:
        """Look up a contract by ID. Returns None if not found."""
        return self.runtime.contracts.get(contract_id)

    def get_receipt(self, receipt_hash: str) -> Receipt | None:
        """Look up a receipt by hash. Returns None if not found."""
        return self.runtime.receipts.get(receipt_hash)

    # ── Receipt queries ────────────────────────────────────────

    def receipts_for_contract(self, contract_id: str) -> list[Receipt]:
        """All receipts for a contract, in append order."""
        return self.runtime.receipts.for_contract(contract_id)

    def receipts_for_scope(self, scope_id: str) -> list[Receipt]:
        """All receipts for a scope, in append order."""
        return self.runtime.receipts.for_scope(scope_id)

    # ── Budget queries ─────────────────────────────────────────

    def get_budget_balance(self, scope_id: str, dimension: str) -> Decimal | None:
        """Remaining budget (ceiling − consumed) for a scope+dimension.

        Returns None if no ceiling is registered for this pair.
        """
        return self.runtime.budget.get_balance(scope_id, dimension)

    # ── Convenience accessors ─────────────────────────────────

    @property
    def receipts(self):
        return self.runtime.receipts

    @property
    def scopes(self):
        return self.runtime.scopes

    @property
    def contracts(self):
        return self.runtime.contracts
