"""VMIP 0.1 Cross-Vendor Tool Marketplace — End-to-End Demo.

Built on vincul SDK high-level constructs:
  - VinculContext (one-stop coalition setup)
  - @vincul_tool / @tool_operation (declarative tool definition)
  - VinculAgent (agent base with invoke())
  - ToolResult (unified return type)

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

from vincul.identity import verify
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


def run_demo() -> None:
    """Run the full cross-vendor marketplace demo on vincul SDK."""

    # ==================================================================
    # STEP 1: Vendor Setup — VinculContext handles everything
    # ==================================================================
    _section("STEP 1: Vendor Setup (VinculContext.add_principal)")

    ctx = VinculContext()
    key_a = ctx.add_principal(VENDOR_A_ID, role="agent_host", permissions=["delegate", "commit"])
    key_b = ctx.add_principal(VENDOR_B_ID, role="tool_provider", permissions=["delegate", "commit", "revoke"])
    key_c = ctx.add_principal(VENDOR_C_ID, role="data_provider", permissions=["commit"])

    print(f"  Vendor A: {key_a.principal_id}  pubkey={key_a.public_key_b64()[:20]}...")
    print(f"  Vendor B: {key_b.principal_id}  pubkey={key_b.public_key_b64()[:20]}...")
    print(f"  Vendor C: {key_c.principal_id}  pubkey={key_c.public_key_b64()[:20]}...")

    # Tool provider (decorated with @vincul_tool)
    tool_provider = VendorBToolProvider(key_pair=key_b, runtime=ctx.runtime)

    print(f"\n  Tool Manifest: {tool_provider.tool_manifest['tool_id']}")
    print(f"  Operations: {[op['name'] for op in tool_provider.tool_manifest['operations']]}")

    # ==================================================================
    # STEP 2: Contract — one call
    # ==================================================================
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

    # ==================================================================
    # STEP 3: Scope Chain — one call
    # ==================================================================
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

    # ==================================================================
    # STEP 4: Agent setup + successful invocation
    # ==================================================================
    _section("STEP 4: Tool Invocation — place_order (should SUCCEED)")

    agent = VendorABuyerAgent(
        agent_id=AGENT_ID,
        contract=contract,
        scope=leaf,
    )

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

    # Verify attested result signature
    sig = attested["signature"]
    valid = verify(
        key_b.public_key,
        attested["result_payload_hash"].encode("utf-8"),
        sig["sig"],
    )
    print(f"  Attested result signature: {'VALID' if valid else 'INVALID'}")

    # ==================================================================
    # STEP 5: Second Invocation
    # ==================================================================
    _section("STEP 5: Second Invocation (should SUCCEED)")

    result2 = agent.buy(
        tool_provider,
        item_id="book-456",
        quantity=2,
        shipping_zip="94102",
    )
    print(f"  Status: {result2.attested_result['status']}")
    print(f"  Order ID: {result2.payload['order_id']}")
    print(f"  Charged: ${result2.payload['charged_amount_usd']}")

    # ==================================================================
    # STEP 6: Revocation
    # ==================================================================
    _section("STEP 6: Revocation — VendorB revokes mid scope (cascade)")

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

    # ==================================================================
    # STEP 7: Post-Revocation (fail-closed)
    # ==================================================================
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

    # ==================================================================
    # STEP 8: Receipt Log Audit Trail
    # ==================================================================
    _section("STEP 8: Receipt Log (vincul.receipts.ReceiptLog)")

    timeline = ctx.receipts.timeline()
    print(f"  Total receipts: {len(timeline)}")
    for i, r in enumerate(timeline):
        kind = r.receipt_kind.value
        print(f"    [{i}] {kind:25s} | {r.outcome:7s} | {r.receipt_hash[:32]}...")

    all_valid = all(r.verify_hash() for r in timeline)
    print(f"\n  All receipt hashes valid: {all_valid}")

    # ==================================================================
    # STEP 9: Constraint violation (quantity > ceiling)
    # ==================================================================
    _section("STEP 9: Constraint Violation (quantity exceeds ceiling)")

    # Re-create scope chain (old ones are revoked)
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

    # ==================================================================
    # Summary
    # ==================================================================
    _section("DEMO COMPLETE")

    print("  Built on vincul SDK:")
    print(f"    - VinculContext with {len(ctx.contracts)} contract(s)")
    print(f"    - ScopeStore with {len(ctx.scopes)} scope(s)")
    print(f"    - ReceiptLog with {len(ctx.receipts)} receipt(s)")
    print()
    print("  SDK constructs used:")
    print("    - VinculContext (one-stop coalition setup)")
    print("    - @vincul_tool + @tool_operation (declarative tool definition)")
    print("    - @vincul_agent + @agent_action (declarative agent definition)")
    print("    - ToolResult (unified return type)")
    print("    - Automatic: 7-step pipeline, receipts, attested results")
    print()


if __name__ == "__main__":
    run_demo()
