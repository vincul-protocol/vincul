"""
apps.server.demo_state — DemoState singleton

Wires PactRuntime + fixture data for the 8-friends-trip scenario.
Deterministic: every reset() produces identical state.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

from pact.contract import CoalitionContract
from pact.receipts import Receipt
from pact.runtime import PactRuntime
from pact.scopes import Scope
from pact.types import Domain, OperationType, ReceiptKind

from connectors.flights import FlightsConnector
from connectors.hotels import HotelsConnector


# ── Stable identifiers ───────────────────────────────────────

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

CONTRACT_ID = "c0000000-0000-0000-0000-000000000001"
ROOT_SCOPE_ID = "s0000000-0000-0000-0000-000000000001"
RAANAN_FLIGHTS_ID = "s0000000-0000-0000-0000-000000000002"
YAKI_ACCOMMODATION_ID = "s0000000-0000-0000-0000-000000000003"

ACTIVATED_AT = "2026-01-01T00:00:00Z"
EXPIRES_AT = "2027-12-31T23:59:59Z"


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
    Singleton demo state. Wraps PactRuntime + connectors + votes.

    Call setup_contract() after construction to initialize the
    8-friends-trip scenario.
    """

    def __init__(self) -> None:
        self.runtime = PactRuntime()
        self.connectors = {
            "flights": FlightsConnector(),
            "hotels": HotelsConnector(),
        }
        self.votes: dict[str, VoteSession] = {}
        self._setup_complete = False

    def reset(self) -> dict:
        """Re-initialize everything. Deterministic."""
        self.__init__()
        return {"status": "reset"}

    @property
    def is_setup(self) -> bool:
        return self._setup_complete

    # ── Flow 1: Contract formation ────────────────────────────

    def setup_contract(self) -> dict:
        """
        Create the 8-friends-trip contract, activate it, and set up
        the root scope + two delegated scopes.

        Returns a summary dict.
        """
        if self._setup_complete:
            return {"status": "already_setup", "contract_id": CONTRACT_ID}

        # 1. Register draft contract
        contract = CoalitionContract(
            contract_id=CONTRACT_ID,
            version="0.2",
            purpose={
                "title": "Group Trip to Italy",
                "description": "8 friends coordinating flights and accommodation in Italy",
                "expires_at": EXPIRES_AT,
            },
            principals=[
                {"principal_id": p, "role": "member"} for p in PRINCIPALS
            ],
            governance={
                "decision_rule": "threshold",
                "threshold": 5,
                "amendment_rule": "threshold",
                "amendment_threshold": 6,
            },
            budget_policy={
                "allowed": True,
                "dimensions": [
                    {"name": "EUR", "unit": "EUR", "ceiling": "3000.00"},
                ],
            },
            activation={
                "status": "draft",
                "activated_at": None,
                "dissolved_at": None,
            },
        )
        self.runtime.register_contract(contract)

        # 2. Activate with all 8 signatures
        self.runtime.activate_contract(
            CONTRACT_ID, ACTIVATED_AT, PRINCIPALS,
        )

        # 3. Root scope — travel, full types, TOP/TOP, delegate=True
        root_scope = Scope(
            id=ROOT_SCOPE_ID,
            issued_by_scope_id=None,
            issued_by=CONTRACT_ID,
            issued_at=ACTIVATED_AT,
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
        self.runtime.scopes.add(root_scope)

        # 4. Raanan's flights scope — travel.flights, all types, ceiling ≤ 1500 EUR
        raanan_flights = Scope(
            id=RAANAN_FLIGHTS_ID,
            issued_by_scope_id=ROOT_SCOPE_ID,
            issued_by="principal:coordinator",
            issued_at=ACTIVATED_AT,
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace="travel.flights",
                types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
            ),
            predicate="TOP",
            ceiling="action.params.cost <= 1500",
            delegate=False,
            revoke="principal_only",
        )
        self.runtime.scopes.add(raanan_flights)

        # 5. Yaki's accommodation scope — travel.accommodation, OBSERVE+PROPOSE only
        yaki_accommodation = Scope(
            id=YAKI_ACCOMMODATION_ID,
            issued_by_scope_id=ROOT_SCOPE_ID,
            issued_by="principal:coordinator",
            issued_at=ACTIVATED_AT,
            expires_at=EXPIRES_AT,
            domain=Domain(
                namespace="travel.accommodation",
                types=(OperationType.OBSERVE, OperationType.PROPOSE),
            ),
            predicate="TOP",
            ceiling="action.params.cost <= 1500",
            delegate=False,
            revoke="principal_only",
        )
        self.runtime.scopes.add(yaki_accommodation)

        # 6. Set budget ceilings
        self.runtime.budget.set_ceiling(ROOT_SCOPE_ID, "EUR", "3000.00")
        self.runtime.budget.set_ceiling(RAANAN_FLIGHTS_ID, "EUR", "1500.00")
        self.runtime.budget.set_ceiling(YAKI_ACCOMMODATION_ID, "EUR", "1500.00")

        self._setup_complete = True

        return {
            "status": "setup_complete",
            "contract_id": CONTRACT_ID,
            "contract_hash": self.runtime.contracts.get(CONTRACT_ID).descriptor_hash,
            "scopes": {
                "root": ROOT_SCOPE_ID,
                "raanan_flights": RAANAN_FLIGHTS_ID,
                "yaki_accommodation": YAKI_ACCOMMODATION_ID,
            },
            "principals": PRINCIPALS,
        }

    # ── Flow 2/3: Commit action ───────────────────────────────

    def commit_action(
        self,
        principal: str,
        scope_id: str,
        action: dict[str, Any],
        budget_amounts: dict[str, str] | None = None,
    ) -> Receipt:
        """
        Execute a COMMIT through the runtime.

        On success: calls the appropriate connector stub, then commits
        with the external_ref.
        On failure: returns the failure receipt directly.
        """
        # Pre-validate to decide if we should call the connector
        result = self.runtime.validator.validate_action(
            action, scope_id, CONTRACT_ID,
            budget_amounts=budget_amounts,
        )

        if not result:
            # Emit failure receipt through runtime
            return self.runtime.commit(
                action=action,
                scope_id=scope_id,
                contract_id=CONTRACT_ID,
                initiated_by=principal,
                budget_amounts=budget_amounts,
            )

        # Determine which connector to use based on namespace
        ns = action.get("namespace", "")
        connector_key = None
        if "flights" in ns:
            connector_key = "flights"
        elif "accommodation" in ns or "hotels" in ns:
            connector_key = "hotels"

        external_ref = None
        reversible = False
        revert_window = None

        if connector_key and connector_key in self.connectors:
            connector = self.connectors[connector_key]
            connector_result = connector.book(
                action.get("resource", ""),
                action.get("params", {}),
            )
            external_ref = connector_result.external_ref
            reversible = connector_result.reversible
            revert_window = connector_result.revert_window

        return self.runtime.commit(
            action=action,
            scope_id=scope_id,
            contract_id=CONTRACT_ID,
            initiated_by=principal,
            reversible=reversible,
            revert_window=revert_window,
            external_ref=external_ref,
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

        Returns (session, receipt_or_none). Receipt is non-None only
        when the vote passes and a new delegation is issued.
        """
        session = self.votes.get(vote_id)
        if session is None:
            raise KeyError(f"Vote {vote_id!r} not found.")
        if session.resolved:
            return session, None
        if principal in session.votes_for:
            return session, None  # already voted

        session.votes_for.append(principal)

        receipt = None
        if len(session.votes_for) >= session.threshold:
            # Vote passes — issue new delegation
            receipt = self._resolve_vote(session)

        return session, receipt

    def _resolve_vote(self, session: VoteSession) -> Receipt:
        """Issue a new delegation based on a passing vote."""
        new_scope_id = f"s0000000-0000-0000-0000-{uuid_mod.uuid4().hex[:12]}"
        session.resolved = True
        session.new_scope_id = new_scope_id

        # Build the widened scope
        types = tuple(OperationType(t) for t in session.requested_types)
        parent = self.runtime.scopes.get_or_raise(session.scope_id)

        child = Scope(
            id=new_scope_id,
            issued_by_scope_id=parent.issued_by_scope_id or parent.id,
            issued_by="principal:coordinator",
            issued_at=ACTIVATED_AT,
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

        # Use runtime.delegate to get a proper delegation receipt
        parent_scope_id = parent.issued_by_scope_id or parent.id
        receipt = self.runtime.delegate(
            parent_scope_id=parent_scope_id,
            child=child,
            contract_id=CONTRACT_ID,
            initiated_by="principal:coordinator",
        )

        # Set budget ceiling for the new scope if delegation succeeded
        if receipt.outcome == "success":
            self.runtime.budget.set_ceiling(new_scope_id, "EUR", "1500.00")

        return receipt

    # ── Flow 5: Dissolve ──────────────────────────────────────

    def dissolve(
        self,
        initiated_by: str,
        signatures: list[str],
    ) -> list[Receipt]:
        """
        Dissolve the contract and revoke all scopes.

        Returns list of receipts (dissolution + revocations).
        """
        receipts: list[Receipt] = []

        # Dissolve contract
        dissolution = self.runtime.dissolve_contract(
            contract_id=CONTRACT_ID,
            dissolved_at="2026-07-01T00:00:00Z",
            dissolved_by=initiated_by,
            signatures=signatures,
        )
        receipts.append(dissolution)

        # Revoke root scope (cascades to all children)
        rev_receipt, rev_result = self.runtime.revoke(
            scope_id=ROOT_SCOPE_ID,
            contract_id=CONTRACT_ID,
            initiated_by=initiated_by,
        )
        receipts.append(rev_receipt)

        return receipts

    # ── Enriched state (for frontend) ─────────────────────────

    # Scope-to-principal mapping — demo fixture knowledge, not protocol concept
    _SCOPE_PRINCIPAL_MAP: dict[str, str] = {
        ROOT_SCOPE_ID: "principal:coordinator",
        RAANAN_FLIGHTS_ID: "principal:raanan",
        YAKI_ACCOMMODATION_ID: "principal:yaki",
    }

    def enriched_state(self) -> dict:
        """Return enriched demo state for GET /demo/state."""
        contract = self.runtime.contracts.get(CONTRACT_ID)
        if not contract:
            return {"contract": None, "principals": [], "governance": {},
                    "budget_policy": {}, "scopes": [], "receipt_count": 0}

        # Build scope list with principal assignments
        scope_principal_map = dict(self._SCOPE_PRINCIPAL_MAP)
        for vote in self.votes.values():
            if vote.new_scope_id:
                scope_principal_map[vote.new_scope_id] = "principal:yaki"

        all_scope_ids = [ROOT_SCOPE_ID, RAANAN_FLIGHTS_ID, YAKI_ACCOMMODATION_ID]
        for vote in self.votes.values():
            if vote.new_scope_id:
                all_scope_ids.append(vote.new_scope_id)

        scopes_list = []
        for sid in all_scope_ids:
            s = self.runtime.scopes.get(sid)
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
                "id": CONTRACT_ID,
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
            "receipt_count": len(self.runtime.receipts),
        }

    # ── Status ────────────────────────────────────────────────

    def status_summary(self) -> dict:
        """Return current demo state for GET /demo/status."""
        contract = self.runtime.contracts.get(CONTRACT_ID)
        scopes_list = []
        for sid in [ROOT_SCOPE_ID, RAANAN_FLIGHTS_ID, YAKI_ACCOMMODATION_ID]:
            s = self.runtime.scopes.get(sid)
            if s:
                scopes_list.append({
                    "id": s.id,
                    "namespace": s.domain.namespace,
                    "types": [t.value for t in s.domain.types],
                    "status": s.status.value,
                })

        # Include dynamically created scopes from votes
        for vote in self.votes.values():
            if vote.new_scope_id:
                s = self.runtime.scopes.get(vote.new_scope_id)
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
                "id": CONTRACT_ID,
                "status": contract.activation["status"] if contract else None,
                "hash": contract.descriptor_hash if contract else None,
            },
            "scopes": scopes_list,
            "receipt_count": len(self.runtime.receipts),
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
