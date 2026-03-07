"""vincul.sdk.context — VinculContext: one-stop coalition setup.

Handles principal registration, contract creation/activation, and
scope chain construction in a few calls. Wraps VinculRuntime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from vincul.contract import CoalitionContract
from vincul.identity import KeyPair, PrincipalRegistry
from vincul.receipts import new_uuid, now_utc
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
        budget_allowed: bool = False,
        budget_dimensions: list[dict] | None = None,
        signatories: list[str] | None = None,
    ) -> CoalitionContract:
        """Create, register, and activate a coalition contract.

        Uses all registered principals. Governance defaults to unanimous.
        Returns the activated contract.
        """
        contract = CoalitionContract(
            contract_id=new_uuid(),
            version="0.2",
            purpose={
                "title": purpose_title,
                "description": purpose_description,
                "expires_at": expires_at,
            },
            principals=list(self._principals),
            governance={
                "decision_rule": governance_rule,
                "threshold": None,
            },
            budget_policy={
                "allowed": budget_allowed,
                "dimensions": budget_dimensions,
            },
            activation={"status": "draft"},
        )

        contract = self.runtime.register_contract(contract)

        sigs = signatories or [p["principal_id"] for p in self._principals]
        self.runtime.activate_contract(
            contract.contract_id,
            activated_at=now_utc(),
            signatures=sigs,
        )
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

    # ── Revocation shortcut ───────────────────────────────────

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
