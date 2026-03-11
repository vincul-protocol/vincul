"""
Scenario setup for the OpenClaw + Vincul demo.

Creates the coalition contract, scopes, and principal definitions
for Acts 2 and 3. Act 1 runs without Vincul enforcement.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from vincul.contract import CoalitionContract
from vincul.runtime import VinculRuntime
from vincul.scopes import Scope
from vincul.types import Domain, OperationType, ScopeStatus


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _future_iso() -> str:
    """1 year from now."""
    return "2027-03-11T00:00:00Z"


# Principal IDs
ALICE_PRINCIPAL = "alice"
BOB_PRINCIPAL = "bob"
ALICE_AGENT = "alice-agent"
BOB_AGENT = "bob-agent"

# Contract + scope IDs (stable for demo)
CONTRACT_ID = "c0000000-0000-0000-0000-000000000001"

# Alice's scopes
ALICE_ROOT_SCOPE = "s0000000-0000-0000-0000-alice-root00"
ALICE_MESSAGING_SCOPE = "s0000000-0000-0000-0000-alice-msg00"
ALICE_A2A_SCOPE = "s0000000-0000-0000-0000-alice-a2a00"
ALICE_CALENDAR_SCOPE = "s0000000-0000-0000-0000-alice-cal00"
ALICE_DATA_SCOPE = "s0000000-0000-0000-0000-alice-data0"

# Bob's scopes
BOB_ROOT_SCOPE = "s0000000-0000-0000-0000-bob-root000"
BOB_MESSAGING_SCOPE = "s0000000-0000-0000-0000-bob-msg000"
BOB_A2A_SCOPE = "s0000000-0000-0000-0000-bob-a2a000"
BOB_CALENDAR_SCOPE = "s0000000-0000-0000-0000-bob-cal000"
BOB_BOOKING_SCOPE = "s0000000-0000-0000-0000-bob-book00"


def setup_scenario() -> VinculRuntime:
    """
    Create a VinculRuntime with the full demo scenario:
    - Coalition contract between Alice and Bob
    - Scoped delegation chains for both agents
    """
    rt = VinculRuntime()
    now = _now_iso()
    expires = _future_iso()

    # ── Coalition Contract ─────────────────────────────────────
    contract = CoalitionContract(
        contract_id=CONTRACT_ID,
        version="0.2.0",
        purpose={
            "title": "Alice and Bob agent coordination",
            "domain": "gateway",
        },
        principals=[
            {"principal_id": ALICE_PRINCIPAL, "role": "owner", "display_name": "Alice"},
            {"principal_id": BOB_PRINCIPAL, "role": "owner", "display_name": "Bob"},
        ],
        governance={
            "decision_rule": "unanimous",
            "signatories": [ALICE_PRINCIPAL, BOB_PRINCIPAL],
        },
        budget_policy={"allowed": False, "dimensions": None},
        activation={
            "status": "draft",
            "min_signatures": 2,
            "activated_at": None,
        },
    )
    rt.register_contract(contract)
    rt.activate_contract(
        CONTRACT_ID, now, [ALICE_PRINCIPAL, BOB_PRINCIPAL],
    )

    # ── Alice's agent scopes ──────────────────────────────────

    # Root scope (delegation anchor for cascade revocation)
    alice_root = Scope(
        id=ALICE_ROOT_SCOPE,
        issued_by_scope_id=None,
        issued_by=ALICE_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=True,
        revoke="principal_only",
    )
    rt.scopes.add(alice_root)

    # gateway.messaging.alice — full access to own messages
    alice_msg = Scope(
        id=ALICE_MESSAGING_SCOPE,
        issued_by_scope_id=ALICE_ROOT_SCOPE,
        issued_by=ALICE_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.messaging.alice",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(alice_msg)

    # gateway.a2a — OBSERVE + PROPOSE only (no COMMIT)
    alice_a2a = Scope(
        id=ALICE_A2A_SCOPE,
        issued_by_scope_id=ALICE_ROOT_SCOPE,
        issued_by=ALICE_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.a2a",
            types=(OperationType.OBSERVE, OperationType.PROPOSE),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(alice_a2a)

    # gateway.calendar.alice — read-only
    alice_cal = Scope(
        id=ALICE_CALENDAR_SCOPE,
        issued_by_scope_id=ALICE_ROOT_SCOPE,
        issued_by=ALICE_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.calendar.alice",
            types=(OperationType.OBSERVE,),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(alice_cal)

    # gateway.data.alice — read-only
    alice_data = Scope(
        id=ALICE_DATA_SCOPE,
        issued_by_scope_id=ALICE_ROOT_SCOPE,
        issued_by=ALICE_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.data.alice",
            types=(OperationType.OBSERVE,),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(alice_data)

    # ── Bob's agent scopes ────────────────────────────────────

    bob_root = Scope(
        id=BOB_ROOT_SCOPE,
        issued_by_scope_id=None,
        issued_by=BOB_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=True,
        revoke="principal_only",
    )
    rt.scopes.add(bob_root)

    bob_msg = Scope(
        id=BOB_MESSAGING_SCOPE,
        issued_by_scope_id=BOB_ROOT_SCOPE,
        issued_by=BOB_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.messaging.bob",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(bob_msg)

    bob_a2a = Scope(
        id=BOB_A2A_SCOPE,
        issued_by_scope_id=BOB_ROOT_SCOPE,
        issued_by=BOB_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.a2a",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(bob_a2a)

    bob_cal = Scope(
        id=BOB_CALENDAR_SCOPE,
        issued_by_scope_id=BOB_ROOT_SCOPE,
        issued_by=BOB_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.calendar.bob",
            types=(OperationType.OBSERVE,),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(bob_cal)

    bob_booking = Scope(
        id=BOB_BOOKING_SCOPE,
        issued_by_scope_id=BOB_ROOT_SCOPE,
        issued_by=BOB_PRINCIPAL,
        issued_at=now,
        expires_at=expires,
        domain=Domain(
            namespace="gateway.booking",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )
    rt.scopes.add(bob_booking)

    return rt


# Mapping: agent name → list of scope IDs (ordered: most specific first)
AGENT_SCOPES: dict[str, list[str]] = {
    "alice-agent": [
        ALICE_MESSAGING_SCOPE,
        ALICE_A2A_SCOPE,
        ALICE_CALENDAR_SCOPE,
        ALICE_DATA_SCOPE,
        ALICE_ROOT_SCOPE,
    ],
    "bob-agent": [
        BOB_MESSAGING_SCOPE,
        BOB_A2A_SCOPE,
        BOB_CALENDAR_SCOPE,
        BOB_BOOKING_SCOPE,
        BOB_ROOT_SCOPE,
    ],
}
