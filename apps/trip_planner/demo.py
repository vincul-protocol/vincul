"""8-Friends Trip Planner — End-to-End CLI Demo.

Usage:
    python -m apps.trip_planner.demo

Exercises the full DemoState flow:
  1. Contract setup (8 principals, root + 2 delegated scopes, budgets)
  2. Raanan books a flight (should SUCCEED)
  3. Yaki tries to book accommodation (should FAIL — no COMMIT type)
  4. Governance vote to widen Yaki's scope (5 votes → passes)
  5. Yaki books with new scope (should SUCCEED)
  6. Budget violation (should FAIL — cost exceeds ceiling)
  7. Contract dissolution
  8. Audit trail
"""

from __future__ import annotations

from .state import DemoState, PRINCIPALS


def _section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def run_demo() -> None:
    state = DemoState()

    # ==================================================================
    # STEP 1: Contract Setup
    # ==================================================================
    _section("STEP 1: Contract Setup (8 friends, scopes, budgets)")

    result = state.setup_contract()
    print(f"  Status: {result['status']}")
    print(f"  Contract ID: {result['contract_id']}")
    print(f"  Contract hash: {result['contract_hash'][:32]}...")
    print(f"  Principals: {len(result['principals'])}")
    for label, sid in result["scopes"].items():
        print(f"  Scope {label}: {sid[:20]}...")

    # ==================================================================
    # STEP 2: Raanan books a flight (should SUCCEED)
    # ==================================================================
    _section("STEP 2: Raanan Books Flight (should SUCCEED)")

    flight_result = state.commit_action(
        principal="principal:raanan",
        scope_id=state.flights_scope.id,
        action={
            "namespace": "travel.flights",
            "resource": "FCO-TLV-2027-06-15",
            "params": {"cost": 450},
        },
        budget_amounts={"EUR": "450.00"},
    )

    print(f"  Success: {flight_result.success}")
    print(f"  Receipt kind: {flight_result.receipt.receipt_kind.value}")
    print(f"  Receipt hash: {flight_result.receipt.receipt_hash[:32]}...")
    if flight_result.success:
        print(f"  External ref: {flight_result.payload['external_ref']}")
        print(f"  Reversible: {flight_result.payload['reversible']}")

    # ==================================================================
    # STEP 3: Yaki tries accommodation (should FAIL — no COMMIT)
    # ==================================================================
    _section("STEP 3: Yaki Books Accommodation (should FAIL — no COMMIT type)")

    accom_result = state.commit_action(
        principal="principal:yaki",
        scope_id=state.accommodation_scope.id,
        action={
            "namespace": "travel.accommodation",
            "resource": "Hotel-Roma-Centro",
            "params": {"cost": 800},
        },
        budget_amounts={"EUR": "800.00"},
    )

    print(f"  Success: {accom_result.success}")
    print(f"  Failure code: {accom_result.failure_code}")
    print(f"  Message: {accom_result.message}")

    # ==================================================================
    # STEP 4: Governance vote to widen Yaki's scope
    # ==================================================================
    _section("STEP 4: Governance Vote (widen Yaki's scope to include COMMIT)")

    session = state.open_vote(
        scope_id=state.accommodation_scope.id,
        request="Add COMMIT to Yaki's accommodation scope",
        requested_types=["OBSERVE", "PROPOSE", "COMMIT"],
        requested_ceiling="action.params.cost <= 1500",
    )
    print(f"  Vote ID: {session.vote_id}")
    print(f"  Threshold: {session.threshold}")

    voters = PRINCIPALS[:5]  # First 5 principals vote
    for voter in voters:
        session, receipt = state.cast_vote(session.vote_id, voter)
        status = "RESOLVED" if session.resolved else f"{len(session.votes_for)}/{session.threshold}"
        print(f"  {voter.split(':')[1]:12s} voted — {status}")

    print(f"\n  Vote resolved: {session.resolved}")
    print(f"  New scope ID: {session.new_scope_id[:20]}...")
    if receipt:
        print(f"  Delegation receipt: {receipt.receipt_hash[:32]}...")

    # ==================================================================
    # STEP 5: Yaki books with new scope (should SUCCEED)
    # ==================================================================
    _section("STEP 5: Yaki Books with New Scope (should SUCCEED)")

    accom_result2 = state.commit_action(
        principal="principal:yaki",
        scope_id=session.new_scope_id,
        action={
            "namespace": "travel.accommodation",
            "resource": "Hotel-Roma-Centro",
            "params": {"cost": 800},
        },
        budget_amounts={"EUR": "800.00"},
    )

    print(f"  Success: {accom_result2.success}")
    print(f"  Receipt kind: {accom_result2.receipt.receipt_kind.value}")
    if accom_result2.success:
        print(f"  External ref: {accom_result2.payload['external_ref']}")
        print(f"  Reversible: {accom_result2.payload['reversible']}")
        print(f"  Revert window: {accom_result2.payload['revert_window']}")

    # ==================================================================
    # STEP 6: Budget violation (should FAIL)
    # ==================================================================
    _section("STEP 6: Budget Violation (cost exceeds ceiling)")

    expensive = state.commit_action(
        principal="principal:raanan",
        scope_id=state.flights_scope.id,
        action={
            "namespace": "travel.flights",
            "resource": "First-Class-FCO-TLV",
            "params": {"cost": 9999},
        },
        budget_amounts={"EUR": "9999.00"},
    )

    print(f"  Success: {expensive.success}")
    print(f"  Failure code: {expensive.failure_code}")
    print(f"  Message: {expensive.message}")

    # ==================================================================
    # STEP 7: Dissolve
    # ==================================================================
    _section("STEP 7: Contract Dissolution")

    receipts = state.dissolve(
        initiated_by="principal:coordinator",
        signatures=[p for p in PRINCIPALS],
    )

    for r in receipts:
        print(f"  {r.receipt_kind.value:25s} | {r.outcome} | {r.receipt_hash[:32]}...")

    # ==================================================================
    # STEP 8: Audit trail
    # ==================================================================
    _section("STEP 8: Audit Trail")

    timeline = state.ctx.receipts.timeline()
    print(f"  Total receipts: {len(timeline)}")
    for i, r in enumerate(timeline):
        kind = r.receipt_kind.value
        print(f"    [{i}] {kind:25s} | {r.outcome:7s} | {r.receipt_hash[:32]}...")

    all_valid = all(r.verify_hash() for r in timeline)
    print(f"\n  All receipt hashes valid: {all_valid}")

    # ==================================================================
    # Summary
    # ==================================================================
    _section("DEMO COMPLETE")

    print("  8-Friends Trip Planner — vincul SDK")
    print(f"    - {len(PRINCIPALS)} principals")
    print(f"    - {len(state.ctx.contracts)} contract(s)")
    print(f"    - {len(state.ctx.scopes)} scope(s)")
    print(f"    - {len(timeline)} receipt(s)")
    print()


if __name__ == "__main__":
    run_demo()
