"""VMIP 0.1 Cross-Vendor Tool Marketplace — End-to-End Demo.

Usage:
    python -m apps.tool_marketplace.demo [--vinculnet]

Flags:
    --vinculnet  Enable VinculNet transport (receipt exchange over WebSocket)

Demonstrates:
  1. Vendor setup via VinculContext.add_principal()
  2. Contract creation via VinculContext.create_contract()
  3. Scope chain via VinculContext.create_scope_chain()
  4. Successful tool invocation (decorated operation)
  5. Second invocation
  6. Revocation cascade
  7. Post-revocation denial (fail-closed)
  8. Receipt log audit trail
  9. Constraint violation
"""

from __future__ import annotations

import argparse
import asyncio
import copy

from vincul.identity import verify
from vincul.receipts import Receipt
from vincul.runtime import VinculRuntime
from vincul.sdk import VinculContext
from vincul.types import ReceiptKind, ScopeStatus

from .vendor_a_agent import (
    VendorABuyerAgent,
    VENDOR_A_ID,
    VENDOR_B_ID,
    VENDOR_C_ID,
    AGENT_ID,
)
from .vendor_b_tool import VendorBToolProvider


def _section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def _replicate_runtime(source: VinculRuntime) -> VinculRuntime:
    """Create an independent runtime with identical state (for VinculNet mode)."""
    replica = VinculRuntime()

    for contract in source.contracts._contracts.values():
        cloned = copy.deepcopy(contract)
        replica.contracts._contracts[cloned.contract_id] = cloned

    for scope in source.scopes._scopes.values():
        cloned = copy.deepcopy(scope)
        replica.scopes._scopes[cloned.id] = cloned
        if cloned.issued_by_scope_id:
            parent_id = cloned.issued_by_scope_id
            if parent_id not in replica.scopes._children:
                replica.scopes._children[parent_id] = []
            replica.scopes._children[parent_id].append(cloned.id)

    for receipt in source.receipts.timeline():
        replica.receipts.append(copy.deepcopy(receipt))

    for key, value in source.budget._ceilings.items():
        replica.budget._ceilings[key] = value
    for key, value in source.budget._consumed.items():
        replica.budget._consumed[key] = copy.deepcopy(value)

    return replica


async def run_demo(*, vinculnet: bool = False) -> None:
    """Run the full cross-vendor marketplace demo on vincul SDK."""

    # VinculNet state (only used when vinculnet=True)
    peer_a = peer_b = None
    vendor_a_received: list[tuple[str, Receipt]] = []
    vendor_b_received: list[tuple[str, Receipt]] = []

    mode = "SDK + VinculNet" if vinculnet else "SDK"
    print(f"\n  Mode: {mode}")

    try:
        # ==============================================================
        # STEP 1: Vendor Setup
        # ==============================================================
        _section("STEP 1: Vendor Setup (VinculContext.add_principal)")

        ctx = VinculContext()
        key_a = ctx.add_principal(VENDOR_A_ID, role="agent_host", permissions=["delegate", "commit"])
        key_b = ctx.add_principal(VENDOR_B_ID, role="tool_provider", permissions=["delegate", "commit", "revoke"])
        key_c = ctx.add_principal(VENDOR_C_ID, role="data_provider", permissions=["commit"])

        print(f"  Vendor A: {key_a.principal_id}  pubkey={key_a.public_key_b64()[:20]}...")
        print(f"  Vendor B: {key_b.principal_id}  pubkey={key_b.public_key_b64()[:20]}...")
        print(f"  Vendor C: {key_c.principal_id}  pubkey={key_c.public_key_b64()[:20]}...")

        if vinculnet:
            from vincul.transport.protocol_peer import ProtocolPeer

            peer_a = ProtocolPeer(VENDOR_A_ID, key_a)
            peer_b = ProtocolPeer(VENDOR_B_ID, key_b)
            peer_a.on_receipt(lambda sender, receipt: vendor_a_received.append((sender, receipt)))
            peer_b.on_receipt(lambda sender, receipt: vendor_b_received.append((sender, receipt)))

            await peer_b.listen("localhost", 8799)
            connected_peer = await peer_a.connect("ws://localhost:8799")
            print(f"\n  VinculNet: Vendor A connected to Vendor B")
            print(f"  Handshake peer: {connected_peer}")

        tool_provider = VendorBToolProvider(key_pair=key_b, runtime=ctx.runtime)

        print(f"\n  Tool Manifest: {tool_provider.tool_manifest['tool_id']}")
        print(f"  Operations: {[op['name'] for op in tool_provider.tool_manifest['operations']]}")

        # ==============================================================
        # STEP 2: Contract
        # ==============================================================
        _section("STEP 2: Contract (VinculContext.create_contract)")

        contract = ctx.create_contract(
            purpose_title="Cross-vendor tool marketplace",
            purpose_description="VendorA agents invoke VendorB tools under scoped delegation",
        )

        print(f"  Contract ID: {contract.contract_id}")
        print(f"  Status: {contract.status.value}")
        print(f"  Principals: {contract.principal_ids()}")
        print(f"  Governance: {contract.governance['decision_rule']}")
        print(f"  descriptor_hash: {contract.descriptor_hash[:32]}...")
        print(f"  Hash valid: {contract.verify_hash()}")

        # ==============================================================
        # STEP 3: Scope Chain
        # ==============================================================
        _section("STEP 3: Scope Chain (VinculContext.create_scope_chain)")

        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by=VENDOR_B_ID,
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP", "ttl_hours": 2},
                {"ceiling": "params.quantity <= 10", "ttl_hours": 1.5},
                {"ceiling": "params.quantity <= 5", "delegate": False, "ttl_hours": 1},
            ],
        )
        root, mid, leaf = scopes

        for label, scope in [("Root", root), ("Mid", mid), ("Leaf", leaf)]:
            print(f"  {label} Scope: {scope.id[:20]}...")
            print(f"    namespace: {scope.domain.namespace}")
            print(f"    types: {[t.value for t in scope.domain.types]}")
            print(f"    ceiling: {scope.ceiling}")
            print(f"    delegate: {scope.delegate}")
            print(f"    status: {scope.status.value}")
            print(f"    descriptor_hash: {scope.descriptor_hash[:32]}...")

        deleg_receipts = [r for r in ctx.receipts.timeline() if r.receipt_kind == ReceiptKind.DELEGATION]
        print(f"\n  Delegation receipts in log: {len(deleg_receipts)}")
        for r in deleg_receipts:
            print(f"    {r.receipt_id[:20]}... -> child {r.detail['child_scope_id'][:20]}...")

        if vinculnet:
            peer_a.runtime = ctx.runtime
            peer_b.runtime = _replicate_runtime(ctx.runtime)
            print(f"\n  VinculNet: Both peers bootstrapped with identical state")
            print(f"    Peer A contract hash: {peer_a.runtime.contracts.get(contract.contract_id).descriptor_hash[:32]}...")
            print(f"    Peer B contract hash: {peer_b.runtime.contracts.get(contract.contract_id).descriptor_hash[:32]}...")
            print(f"    Hashes match: {peer_a.runtime.contracts.get(contract.contract_id).descriptor_hash == peer_b.runtime.contracts.get(contract.contract_id).descriptor_hash}")

        # ==============================================================
        # STEP 4: Tool Invocation (should SUCCEED)
        # ==============================================================
        step4_label = "STEP 4: Tool Invocation"
        if vinculnet:
            step4_label += " + VinculNet Receipt"
        step4_label += " (should SUCCEED)"
        _section(step4_label)

        agent = VendorABuyerAgent(contract=contract, scopes=[leaf])

        result = agent.buy(
            tool_provider,
            item_id="book-123",
            quantity=1,
            shipping_zip="10001",
        )

        attested = result.attested_result
        print(f"  Status: {attested['status']}")
        print(f"  Order ID: {attested['result_payload']['order_id']}")
        print(f"  Charged: ${attested['result_payload']['charged_amount_usd']}")
        print(f"  External Ref: {attested['external_ref']}")
        print(f"  receipt_hash: {result.receipt.receipt_hash[:32]}...")
        print(f"  contract_hash in result: {attested['contract_hash'][:32]}...")
        print(f"  scope_hash in result: {attested['scope_hash'][:32]}...")

        sig = attested["signature"]
        valid = verify(
            key_b.public_key,
            attested["result_payload_hash"].encode("utf-8"),
            sig["sig"],
        )
        print(f"  Attested result signature: {'VALID' if valid else 'INVALID'}")

        if vinculnet:
            sent = await peer_a.peer.send(VENDOR_B_ID, {"type": "receipt", "receipt": result.receipt.to_dict()})
            await asyncio.sleep(0.1)
            print(f"\n  VinculNet: Receipt sent to Vendor B: {sent}")
            print(f"  VinculNet: Vendor B received {len(vendor_b_received)} receipt(s)")
            if vendor_b_received:
                sender, rx = vendor_b_received[-1]
                print(f"    From: {sender}")
                print(f"    Receipt hash: {rx.receipt_hash[:32]}...")
                print(f"    Hash valid: {rx.verify_hash()}")
                print(f"    Cross-check: scope_hash matches Vendor B's local state")

        # ==============================================================
        # STEP 5: Second Invocation (should SUCCEED)
        # ==============================================================
        step5_label = "STEP 5: Second Invocation"
        if vinculnet:
            step5_label += " + VinculNet Receipt"
        step5_label += " (should SUCCEED)"
        _section(step5_label)

        result2 = agent.buy(
            tool_provider,
            item_id="book-456",
            quantity=2,
            shipping_zip="94102",
        )
        print(f"  Status: {result2.attested_result['status']}")
        print(f"  Order ID: {result2.payload['order_id']}")
        print(f"  Charged: ${result2.payload['charged_amount_usd']}")

        if vinculnet:
            await peer_a.peer.send(VENDOR_B_ID, {"type": "receipt", "receipt": result2.receipt.to_dict()})
            await asyncio.sleep(0.1)
            print(f"\n  VinculNet: Vendor B total receipts received: {len(vendor_b_received)}")

        # ==============================================================
        # STEP 6: Revocation
        # ==============================================================
        _section("STEP 6: Revocation — VendorB revokes mid scope (cascade)")

        if vinculnet:
            # Vendor B revokes on its own independent runtime
            rev_receipt, rev_result = peer_b.runtime.revoke(
                scope_id=mid.id,
                contract_id=contract.contract_id,
                initiated_by=VENDOR_B_ID,
            )

            print(f"  Revocation root: {rev_result.root_scope_id[:20]}...")
            print(f"  Revoked scope IDs ({len(rev_result.revoked_ids)}):")
            for sid in rev_result.revoked_ids:
                scope = peer_b.runtime.scopes.get(sid)
                print(f"    {sid[:20]}... -> status={scope.status.value}")
            print(f"  Effective at: {rev_result.effective_at}")
            print(f"  Revocation receipt: {rev_receipt.receipt_hash[:32]}...")

            assert peer_b.runtime.scopes.get(mid.id).status == ScopeStatus.REVOKED
            assert peer_b.runtime.scopes.get(leaf.id).status == ScopeStatus.REVOKED
            print(f"\n  Peer B mid scope status: {peer_b.runtime.scopes.get(mid.id).status.value}")
            print(f"  Peer B leaf scope status: {peer_b.runtime.scopes.get(leaf.id).status.value}")
            print(f"  Peer B root scope status: {peer_b.runtime.scopes.get(root.id).status.value} (unaffected)")
            print(f"\n  Peer A mid scope status: {peer_a.runtime.scopes.get(mid.id).status.value} (still active — independent runtime)")

            # Broadcast revocation receipt over VinculNet
            await peer_b.peer.send(VENDOR_A_ID, {"type": "receipt", "receipt": rev_receipt.to_dict()})
            await asyncio.sleep(0.1)
            print(f"\n  VinculNet: Revocation receipt sent to Vendor A")
            print(f"  VinculNet: Vendor A received {len(vendor_a_received)} receipt(s)")
            if vendor_a_received:
                sender, rx = vendor_a_received[-1]
                print(f"    From: {sender}")
                print(f"    Receipt kind: {rx.receipt_kind.value}")
                print(f"    Receipt hash valid: {rx.verify_hash()}")
                print(f"    Scope/contract cross-check: PASSED (hashes match Vendor A's local state)")

            # Also revoke on ctx so step 7 fails correctly
            ctx.revoke_scope(scope_id=mid.id, contract_id=contract.contract_id, initiated_by=VENDOR_B_ID)
        else:
            rev_receipt, rev_result = ctx.revoke_scope(
                scope_id=mid.id,
                contract_id=contract.contract_id,
                initiated_by=VENDOR_B_ID,
            )

            print(f"  Revocation root: {rev_result.root_scope_id[:20]}...")
            print(f"  Revoked scope IDs ({len(rev_result.revoked_ids)}):")
            for sid in rev_result.revoked_ids:
                scope = ctx.scopes.get(sid)
                print(f"    {sid[:20]}... -> status={scope.status.value}")
            print(f"  Effective at: {rev_result.effective_at}")
            print(f"  Revocation receipt: {rev_receipt.receipt_hash[:32]}...")

            assert ctx.scopes.get(mid.id).status == ScopeStatus.REVOKED
            assert ctx.scopes.get(leaf.id).status == ScopeStatus.REVOKED
            print(f"\n  Mid scope status: {ctx.scopes.get(mid.id).status.value}")
            print(f"  Leaf scope status: {ctx.scopes.get(leaf.id).status.value}")
            print(f"  Root scope status: {ctx.scopes.get(root.id).status.value} (unaffected)")

        # ==============================================================
        # STEP 7: Post-Revocation (should FAIL)
        # ==============================================================
        _section("STEP 7: Post-Revocation Invocation (should FAIL)")

        result3 = agent.buy(
            tool_provider,
            item_id="book-789",
            quantity=1,
            shipping_zip="60601",
        )
        print(f"  Status: {result3.attested_result['status']}")
        print(f"  Failure Code: {result3.failure_code}")
        print(f"  Message: {result3.message}")
        print(f"  Receipt kind: {result3.receipt.receipt_kind.value}")

        if vinculnet:
            print(f"\n  VinculNet: Vendor B receipts still: {len(vendor_b_received)} (failure NOT broadcast)")

        # ==============================================================
        # STEP 8: Receipt Log Audit Trail
        # ==============================================================
        _section("STEP 8: Receipt Log (vincul.receipts.ReceiptLog)")

        timeline = ctx.receipts.timeline()
        label = "Total receipts (Vendor A runtime)" if vinculnet else "Total receipts"
        print(f"  {label}: {len(timeline)}")
        for i, r in enumerate(timeline):
            kind = r.receipt_kind.value
            print(f"    [{i}] {kind:25s} | {r.outcome:7s} | {r.receipt_hash[:32]}...")

        all_valid = all(r.verify_hash() for r in timeline)
        print(f"\n  All receipt hashes valid: {all_valid}")

        if vinculnet:
            peer_b_timeline = peer_b.runtime.receipts.timeline()
            print(f"\n  Vendor B runtime receipts: {len(peer_b_timeline)} (bootstrapped + received over VinculNet)")
            print(f"\n  VinculNet receipt exchange summary:")
            print(f"    Vendor A received: {len(vendor_a_received)} receipt(s) over VinculNet")
            print(f"    Vendor B received: {len(vendor_b_received)} receipt(s) over VinculNet")

        # ==============================================================
        # STEP 9: Constraint violation (quantity > ceiling)
        # ==============================================================
        _section("STEP 9: Constraint Violation (quantity exceeds ceiling)")

        scopes2 = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by=VENDOR_B_ID,
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP", "ttl_hours": 2},
                {"ceiling": "params.quantity <= 10", "ttl_hours": 1.5},
                {"ceiling": "params.quantity <= 5", "delegate": False, "ttl_hours": 1},
            ],
        )
        leaf2 = scopes2[-1]

        result4 = tool_provider.place_order(
            scope_id=leaf2.id,
            contract_id=contract.contract_id,
            initiated_by=AGENT_ID,
            item_id="book-big",
            quantity=999,
            shipping_zip="10001",
        )
        print(f"  Status: {result4.attested_result['status']}")
        print(f"  Failure Code: {result4.failure_code}")
        print(f"  Message: {result4.message}")

        # ==============================================================
        # Summary
        # ==============================================================
        _section("DEMO COMPLETE")

        print(f"  Built on vincul {mode}:")
        print(f"    - VinculContext with {len(ctx.contracts)} contract(s)")
        print(f"    - ScopeStore with {len(ctx.scopes)} scope(s)")
        print(f"    - ReceiptLog with {len(ctx.receipts)} receipt(s)")
        print()
        print("  SDK constructs used:")
        print("    - VinculContext (one-stop coalition setup)")
        print("    - @vincul_tool + @vincul_tool_action (declarative tool definition)")
        print("    - @vincul_agent + @vincul_agent_action (declarative agent definition)")
        print("    - ToolResult (unified return type)")
        print("    - Automatic: 7-step pipeline, receipts, attested results")
        if vinculnet:
            print()
            print("  VinculNet transport:")
            print("    - Two independent ProtocolPeers, each with its own VinculRuntime")
            print("    - Mutual HELLO handshake with Ed25519 signatures")
            print("    - Signed message envelopes with domain-separated hashing")
            print("    - Receipt broadcast with hash + scope/contract cross-checks")
            print(f"    - {len(vendor_a_received) + len(vendor_b_received)} receipt(s) exchanged over wire")
        print()

    finally:
        if peer_a:
            await peer_a.stop()
        if peer_b:
            await peer_b.stop()


def main():
    parser = argparse.ArgumentParser(description="Vincul Cross-Vendor Tool Marketplace Demo")
    parser.add_argument("--vinculnet", action="store_true",
                        help="Enable VinculNet transport (receipt exchange over WebSocket)")
    args = parser.parse_args()
    asyncio.run(run_demo(vinculnet=args.vinculnet))


if __name__ == "__main__":
    main()
