"""
apps.trip_planner.state — DemoState singleton (SDK-driven)

Uses VinculContext + @vincul_tool / @vincul_tool_action for the
8-friends-trip scenario.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

from vincul.identity import KeyPair
from vincul.receipts import Receipt, now_utc
from vincul.runtime import VinculRuntime
from vincul.scopes import Scope
from vincul.sdk import VinculContext, vincul_tool, vincul_tool_action, ToolResult
from vincul.types import Domain, OperationType

from .connectors import FlightsConnector, HotelsConnector


# ── Stable principal identifiers ─────────────────────────────

PRINCIPALS = [
    "principal:raanan",
    "principal:yaki",
    "principal:coordinator",
    "principal:alice",
    "principal:bob",
    "principal:carol",
    "principal:dan",
    "principal:eve",
]

EXPIRES_AT = "2027-12-31T23:59:59Z"


# ── SDK Tool definitions ─────────────────────────────────────

@vincul_tool(namespace="travel.flights", tool_id="tool:trip:flights", tool_version="1.0.0")
class FlightsTool:
    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime):
        self.key_pair = key_pair
        self.runtime = runtime
        self.connector = FlightsConnector()

    @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="resource")
    def book(self, *, resource: str, cost: int) -> dict:
        result = self.connector.book(resource, {"cost": cost})
        return {
            "external_ref": result.external_ref,
            "reversible": result.reversible,
            "revert_window": result.revert_window,
        }


@vincul_tool(namespace="travel.accommodation", tool_id="tool:trip:hotels", tool_version="1.0.0")
class HotelsTool:
    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime):
        self.key_pair = key_pair
        self.runtime = runtime
        self.connector = HotelsConnector()

    @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="resource")
    def book(self, *, resource: str, cost: int) -> dict:
        result = self.connector.book(resource, {"cost": cost})
        return {
            "external_ref": result.external_ref,
            "reversible": result.reversible,
            "revert_window": result.revert_window,
        }


# ── VoteSession (in-demo only) ───────────────────────────────

@dataclass
class VoteSession:
    """Simple in-demo vote session. Not part of the core library."""
    vote_id: str
    scope_id: str
    request: str
    requested_types: list[str]
    requested_ceiling: str
    votes_for: list[str] = field(default_factory=list)
    threshold: int = 5
    resolved: bool = False
    new_scope_id: str | None = None


# ── DemoState ─────────────────────────────────────────────────

class DemoState:
    """
    Singleton demo state using VinculContext + SDK tool decorators.

    Call setup_contract() to initialize the 8-friends-trip scenario.
    """

    def __init__(self) -> None:
        self.ctx: VinculContext | None = None
        self.contract = None
        self.root_scope: Scope | None = None
        self.flights_scope: Scope | None = None
        self.accommodation_scope: Scope | None = None
        self.flights_tool: FlightsTool | None = None
        self.hotels_tool: HotelsTool | None = None
        self.votes: dict[str, VoteSession] = {}
        self._setup_complete = False

    def reset(self) -> dict:
        """Re-initialize everything."""
        self.__init__()
        return {"status": "reset"}

    @property
    def is_setup(self) -> bool:
        return self._setup_complete

    # ── Flow 1: Contract formation ────────────────────────────

    def setup_contract(self) -> dict:
        """
        Create the 8-friends-trip contract via SDK, activate it, and set up
        the root scope + two delegated scopes.
        """
        if self._setup_complete:
            return self._setup_response("already_setup")

        # 1. Create context and register principals
        self.ctx = VinculContext()
        for p in PRINCIPALS:
            self.ctx.add_principal(p, role="member", permissions=["delegate", "commit"])

        # 2. Create and activate contract via SDK
        self.contract = self.ctx.create_contract(
            purpose_title="Group Trip to Italy",
            purpose_description="8 friends coordinating flights and accommodation in Italy",
            expires_at=EXPIRES_AT,
            governance={
                "decision_rule": "threshold",
                "threshold": 5,
                "amendment_rule": "threshold",
                "amendment_threshold": 6,
            },
            budget_allowed=True,
            budget_dimensions=[{"name": "EUR", "unit": "EUR", "ceiling": "3000.00"}],
        )

        # 3. Root scope — travel, full types, TOP/TOP, delegate=True
        self.root_scope = Scope(
            id=str(uuid_mod.uuid4()),
            issued_by_scope_id=None,
            issued_by=self.contract.contract_id,
            issued_at=now_utc(),
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace="travel",
                types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
            ),
            predicate="TOP",
            ceiling="TOP",
            delegate=True,
            revoke="coalition_if_granted",
        )
        self.root_scope = self.ctx.add_scope(self.root_scope)

        # 4. Delegate flights scope for Raanan (all types, cost <= 1500)
        flights_child = Scope(
            id=str(uuid_mod.uuid4()),
            issued_by_scope_id=self.root_scope.id,
            issued_by="principal:coordinator",
            issued_at=now_utc(),
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace="travel.flights",
                types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
            ),
            predicate="action.params.cost <= 1500",
            ceiling="action.params.cost <= 1500",
            delegate=False,
            revoke="principal_only",
        )
        _, self.flights_scope = self.ctx.delegate_scope(
            parent_scope_id=self.root_scope.id,
            child=flights_child,
            contract_id=self.contract.contract_id,
            initiated_by="principal:coordinator",
        )

        # 5. Delegate accommodation scope for Yaki (OBSERVE+PROPOSE only)
        accom_child = Scope(
            id=str(uuid_mod.uuid4()),
            issued_by_scope_id=self.root_scope.id,
            issued_by="principal:coordinator",
            issued_at=now_utc(),
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace="travel.accommodation",
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
            ),
            predicate="action.params.cost <= 1500",
            ceiling="action.params.cost <= 1500",
            delegate=False,
            revoke="principal_only",
        )
        _, self.accommodation_scope = self.ctx.delegate_scope(
            parent_scope_id=self.root_scope.id,
            child=accom_child,
            contract_id=self.contract.contract_id,
            initiated_by="principal:coordinator",
        )

        # 6. Set budget ceilings
        self.ctx.set_budget_ceiling(self.root_scope.id, "EUR", "3000.00")
        self.ctx.set_budget_ceiling(self.flights_scope.id, "EUR", "1500.00")
        self.ctx.set_budget_ceiling(self.accommodation_scope.id, "EUR", "1500.00")

        # 7. Create SDK tool instances
        tool_key = self.ctx.keypair(PRINCIPALS[0])
        self.flights_tool = FlightsTool(key_pair=tool_key, runtime=self.ctx.runtime)
        self.hotels_tool = HotelsTool(key_pair=tool_key, runtime=self.ctx.runtime)

        self._setup_complete = True
        return self._setup_response("setup_complete")

    def _setup_response(self, status: str) -> dict:
        return {
            "status": status,
            "contract_id": self.contract.contract_id,
            "contract_hash": self.contract.descriptor_hash,
            "scopes": {
                "root": self.root_scope.id,
                "raanan_flights": self.flights_scope.id,
                "yaki_accommodation": self.accommodation_scope.id,
            },
            "principals": PRINCIPALS,
        }

    # ── Flow 2/3: Commit action via SDK tools ─────────────────

    def commit_action(
        self,
        principal: str,
        scope_id: str,
        action: dict[str, Any],
        budget_amounts: dict[str, str] | None = None,
    ) -> ToolResult | Receipt:
        """
        Execute a COMMIT through the SDK tool pipeline.

        Routes the generic action dict to the appropriate @vincul_tool_action.
        Returns ToolResult on tool match, Receipt on fallback.
        """
        ns = action.get("namespace", "")
        resource = action.get("resource", "")
        params = action.get("params", {})

        # Route to appropriate tool based on namespace
        tool = None
        if "flights" in ns:
            tool = self.flights_tool
        elif "accommodation" in ns or "hotels" in ns:
            tool = self.hotels_tool

        if tool:
            return tool.book(
                scope_id=scope_id,
                contract_id=self.contract.contract_id,
                initiated_by=principal,
                budget_amounts=budget_amounts,
                resource=resource,
                cost=params.get("cost", 0),
            )

        # Fallback: no tool matched, commit via context
        return self.ctx.commit(
            action=action,
            scope_id=scope_id,
            contract_id=self.contract.contract_id,
            initiated_by=principal,
            budget_amounts=budget_amounts,
        )

    # ── Flow 4: Vote system ───────────────────────────────────

    def open_vote(
        self,
        scope_id: str,
        request: str,
        requested_types: list[str],
        requested_ceiling: str,
    ) -> VoteSession:
        """Open a governance vote to widen a scope."""
        vote_id = str(uuid_mod.uuid4())
        session = VoteSession(
            vote_id=vote_id,
            scope_id=scope_id,
            request=request,
            requested_types=requested_types,
            requested_ceiling=requested_ceiling,
        )
        self.votes[vote_id] = session
        return session

    def cast_vote(self, vote_id: str, principal: str) -> tuple[VoteSession, Receipt | None]:
        """
        Cast a vote. If threshold is met, auto-resolve: issue a new
        delegated scope with the requested permissions.
        """
        session = self.votes.get(vote_id)
        if session is None:
            raise KeyError(f"Vote {vote_id!r} not found.")
        if session.resolved:
            return session, None
        if principal in session.votes_for:
            return session, None

        session.votes_for.append(principal)

        receipt = None
        if len(session.votes_for) >= session.threshold:
            receipt = self._resolve_vote(session)

        return session, receipt

    def _resolve_vote(self, session: VoteSession) -> Receipt:
        """Issue a new delegation based on a passing vote."""
        new_scope_id = str(uuid_mod.uuid4())
        session.resolved = True
        session.new_scope_id = new_scope_id

        types = tuple(OperationType(t) for t in session.requested_types)
        parent = self.ctx.scopes.get_or_raise(session.scope_id)

        child = Scope(
            id=new_scope_id,
            issued_by_scope_id=parent.issued_by_scope_id or parent.id,
            issued_by="principal:coordinator",
            issued_at=now_utc(),
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace=parent.domain.namespace,
                types=types,
            ),
            predicate=session.requested_ceiling,
            ceiling=session.requested_ceiling,
            delegate=False,
            revoke="principal_only",
        )

        parent_scope_id = parent.issued_by_scope_id or parent.id
        receipt, _ = self.ctx.delegate_scope(
            parent_scope_id=parent_scope_id,
            child=child,
            contract_id=self.contract.contract_id,
            initiated_by="principal:coordinator",
        )

        if receipt.outcome == "success":
            self.ctx.set_budget_ceiling(new_scope_id, "EUR", "1500.00")

        return receipt

    # ── Flow 5: Dissolve ──────────────────────────────────────

    def dissolve(
        self,
        initiated_by: str,
        signatures: list[str],
    ) -> list[Receipt]:
        """Dissolve the contract and revoke all scopes."""
        receipts: list[Receipt] = []

        dissolution = self.ctx.dissolve_contract(
            contract_id=self.contract.contract_id,
            dissolved_by=initiated_by,
            signatures=signatures,
        )
        receipts.append(dissolution)

        rev_receipt, _ = self.ctx.revoke_scope(
            scope_id=self.root_scope.id,
            contract_id=self.contract.contract_id,
            initiated_by=initiated_by,
        )
        receipts.append(rev_receipt)

        return receipts

    # ── Enriched state (for frontend) ─────────────────────────

    def enriched_state(self) -> dict:
        """Return enriched demo state for GET /demo/state."""
        if not self.contract:
            return {"contract": None, "principals": [], "governance": {},
                    "budget_policy": {}, "scopes": [], "receipt_count": 0}

        contract = self.ctx.get_contract(self.contract.contract_id)

        # Build scope-to-principal map
        scope_principal_map = {
            self.root_scope.id: "principal:coordinator",
            self.flights_scope.id: "principal:raanan",
            self.accommodation_scope.id: "principal:yaki",
        }
        for vote in self.votes.values():
            if vote.new_scope_id:
                scope_principal_map[vote.new_scope_id] = "principal:yaki"

        all_scope_ids = [self.root_scope.id, self.flights_scope.id, self.accommodation_scope.id]
        for vote in self.votes.values():
            if vote.new_scope_id:
                all_scope_ids.append(vote.new_scope_id)

        scopes_list = []
        for sid in all_scope_ids:
            s = self.ctx.get_scope(sid)
            if s:
                scopes_list.append({
                    "id": s.id,
                    "principal_id": scope_principal_map.get(s.id),
                    "namespace": s.domain.namespace,
                    "types": [t.value for t in s.domain.types],
                    "predicate": s.predicate,
                    "ceiling": s.ceiling,
                    "delegate": s.delegate,
                    "status": s.status.value,
                    "issued_by": s.issued_by,
                    "issued_by_scope_id": s.issued_by_scope_id,
                })

        return {
            "contract": {
                "id": self.contract.contract_id,
                "title": contract.purpose.get("title", ""),
                "description": contract.purpose.get("description", ""),
                "status": contract.activation["status"],
                "hash": contract.descriptor_hash,
                "version": contract.version,
                "expires_at": contract.purpose.get("expires_at"),
            },
            "principals": [
                {"principal_id": p["principal_id"], "role": p["role"]}
                for p in contract.principals
            ],
            "governance": contract.governance,
            "budget_policy": contract.budget_policy,
            "scopes": scopes_list,
            "receipt_count": len(self.ctx.receipts),
        }

    # ── Status ────────────────────────────────────────────────

    def status_summary(self) -> dict:
        """Return current demo state for GET /demo/status."""
        if not self.contract:
            return {
                "setup_complete": False,
                "contract": {"id": None, "status": None, "hash": None},
                "scopes": [],
                "receipt_count": 0,
                "active_votes": {},
            }

        contract = self.ctx.get_contract(self.contract.contract_id)
        all_scope_ids = [self.root_scope.id, self.flights_scope.id, self.accommodation_scope.id]
        for vote in self.votes.values():
            if vote.new_scope_id:
                all_scope_ids.append(vote.new_scope_id)

        scopes_list = []
        for sid in all_scope_ids:
            s = self.ctx.get_scope(sid)
            if s:
                scopes_list.append({
                    "id": s.id,
                    "namespace": s.domain.namespace,
                    "types": [t.value for t in s.domain.types],
                    "status": s.status.value,
                })

        return {
            "setup_complete": self._setup_complete,
            "contract": {
                "id": self.contract.contract_id,
                "status": contract.activation["status"] if contract else None,
                "hash": contract.descriptor_hash if contract else None,
            },
            "scopes": scopes_list,
            "receipt_count": len(self.ctx.receipts),
            "active_votes": {
                vid: {
                    "request": v.request,
                    "votes": len(v.votes_for),
                    "threshold": v.threshold,
                    "resolved": v.resolved,
                }
                for vid, v in self.votes.items()
            },
        }


# ── Module-level singleton ────────────────────────────────────

demo_state = DemoState()
