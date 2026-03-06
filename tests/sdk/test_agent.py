"""
tests/sdk/test_agent.py — @vincul_agent and @agent_action tests (unittest)
"""
import unittest

from vincul.identity import KeyPair
from vincul.runtime import VinculRuntime
from vincul.sdk.agent import agent_action, vincul_agent
from vincul.sdk.context import VinculContext
from vincul.sdk.decorators import ToolResult, tool_operation, vincul_tool
from vincul.types import OperationType, ReceiptKind


# ── Fixtures ─────────────────────────────────────────────────

NAMESPACE = "test.orders"
TOOL_ID = "tool:Test:order-tool"
AGENT_ID = "agent:Test:buyer1"


@vincul_tool(namespace=NAMESPACE, tool_id=TOOL_ID)
class FakeTool:
    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime):
        self.key_pair = key_pair
        self.runtime = runtime

    @tool_operation(action_type=OperationType.COMMIT, resource_key="item_id")
    def place_order(self, *, item_id: str, quantity: int) -> dict:
        return {"order_id": "ord-001", "total": quantity * 10}

    @tool_operation(action_type=OperationType.COMMIT)
    def cancel_order(self, *, order_id: str) -> dict:
        return {"cancelled": order_id}


@vincul_agent(agent_id=AGENT_ID)
class FakeAgent:
    @agent_action(operation="place_order")
    def buy(self, tool, *, item_id: str, quantity: int) -> ToolResult:
        """Buy through the tool."""

    @agent_action
    def cancel_order(self, tool, *, order_id: str) -> ToolResult:
        """Cancel — operation defaults to method name."""


@vincul_agent(agent_id="agent:Test:custom-init")
class AgentWithCustomInit:
    def __init__(self, *, label: str = "default"):
        self.label = label

    @agent_action(operation="place_order")
    def buy(self, tool, *, item_id: str, quantity: int) -> ToolResult:
        """Buy through the tool."""


def _setup(leaf_ceiling="params.quantity <= 10"):
    ctx = VinculContext()
    ctx.add_principal("vendor:A", role="agent", permissions=["delegate", "commit"])
    ctx.add_principal("vendor:B", role="tool", permissions=["delegate", "commit", "revoke"])
    contract = ctx.create_contract(purpose_title="Test marketplace")
    scopes = ctx.create_scope_chain(
        contract_id=contract.contract_id,
        issued_by="vendor:B",
        namespace=NAMESPACE,
        chain=[
            {"ceiling": "TOP"},
            {"ceiling": "TOP"},
            {"ceiling": leaf_ceiling, "delegate": False},
        ],
    )
    tool = FakeTool(key_pair=ctx.keypair("vendor:B"), runtime=ctx.runtime)
    agent = FakeAgent(contract=contract, scope=scopes[2])
    return ctx, contract, scopes, tool, agent


# ── @vincul_agent class decorator ────────────────────────────

class TestVinculAgentDecorator(unittest.TestCase):
    def test_class_metadata(self):
        self.assertEqual(FakeAgent._vincul_agent_id, AGENT_ID)

    def test_agent_id_set(self):
        ctx, contract, scopes, tool, agent = _setup()
        self.assertEqual(agent.agent_id, AGENT_ID)

    def test_contract_bound(self):
        ctx, contract, scopes, tool, agent = _setup()
        self.assertIs(agent.contract, contract)

    def test_scope_bound(self):
        ctx, contract, scopes, tool, agent = _setup()
        self.assertIs(agent.scope, scopes[2])

    def test_invoke_method_added(self):
        ctx, contract, scopes, tool, agent = _setup()
        self.assertTrue(hasattr(agent, "invoke"))
        self.assertTrue(callable(agent.invoke))

    def test_custom_init_preserved(self):
        ctx, contract, scopes, tool, _ = _setup()
        agent = AgentWithCustomInit(contract=contract, scope=scopes[2], label="custom")
        self.assertEqual(agent.label, "custom")
        self.assertEqual(agent.agent_id, "agent:Test:custom-init")

    def test_custom_init_default_kwargs(self):
        ctx, contract, scopes, tool, _ = _setup()
        agent = AgentWithCustomInit(contract=contract, scope=scopes[2])
        self.assertEqual(agent.label, "default")


# ── invoke() ─────────────────────────────────────────────────

class TestAgentInvoke(unittest.TestCase):
    def test_invoke_success(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.invoke(tool, "place_order", item_id="book-1", quantity=2)
        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.success)

    def test_invoke_passes_authority(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.invoke(tool, "place_order", item_id="book-1", quantity=2)
        self.assertEqual(result.receipt.initiated_by, AGENT_ID)
        self.assertEqual(result.receipt.scope_id, scopes[2].id)
        self.assertEqual(result.receipt.contract_id, contract.contract_id)

    def test_invoke_failure(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.invoke(tool, "place_order", item_id="book-1", quantity=999)
        self.assertFalse(result.success)

    def test_invoke_different_operations(self):
        ctx, contract, scopes, tool, agent = _setup(leaf_ceiling="TOP")
        r1 = agent.invoke(tool, "place_order", item_id="book-1", quantity=2)
        r2 = agent.invoke(tool, "cancel_order", order_id="ord-001")
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)


# ── @agent_action — with explicit operation ──────────────────

class TestAgentActionExplicit(unittest.TestCase):
    def test_buy_routes_to_place_order(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.buy(tool, item_id="book-1", quantity=2)
        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.success)
        self.assertIn("order_id", result.payload)

    def test_buy_injects_authority(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.buy(tool, item_id="book-1", quantity=2)
        self.assertEqual(result.receipt.initiated_by, AGENT_ID)

    def test_buy_failure_on_ceiling(self):
        ctx, contract, scopes, tool, agent = _setup()
        result = agent.buy(tool, item_id="book-1", quantity=999)
        self.assertFalse(result.success)

    def test_action_meta(self):
        meta = FakeAgent.buy._vincul_action_meta
        self.assertEqual(meta["name"], "buy")
        self.assertEqual(meta["operation"], "place_order")


# ── @agent_action — without parentheses (operation = method name) ──

class TestAgentActionImplicit(unittest.TestCase):
    def test_cancel_routes_to_cancel_order(self):
        ctx, contract, scopes, tool, agent = _setup(leaf_ceiling="TOP")
        result = agent.cancel_order(tool, order_id="ord-001")
        self.assertTrue(result.success)
        self.assertEqual(result.payload["cancelled"], "ord-001")

    def test_action_meta_implicit(self):
        meta = FakeAgent.cancel_order._vincul_action_meta
        self.assertEqual(meta["name"], "cancel_order")
        self.assertEqual(meta["operation"], "cancel_order")


# ── Post-revocation ──────────────────────────────────────────

class TestAgentPostRevocation(unittest.TestCase):
    def test_agent_action_fails_after_revocation(self):
        ctx, contract, scopes, tool, agent = _setup()
        # Revoke mid scope, cascading to leaf
        ctx.revoke_scope(
            scope_id=scopes[1].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:B",
        )
        result = agent.buy(tool, item_id="book-1", quantity=1)
        self.assertFalse(result.success)
        self.assertIn("REVOKED", result.failure_code or "")

    def test_invoke_fails_after_revocation(self):
        ctx, contract, scopes, tool, agent = _setup()
        ctx.revoke_scope(
            scope_id=scopes[1].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:B",
        )
        result = agent.invoke(tool, "place_order", item_id="book-1", quantity=1)
        self.assertFalse(result.success)


# ── End-to-end: agent + tool + receipts ──────────────────────

class TestAgentToolIntegration(unittest.TestCase):
    def test_receipt_logged(self):
        ctx, contract, scopes, tool, agent = _setup()
        agent.buy(tool, item_id="book-1", quantity=2)
        timeline = ctx.receipts.timeline()
        # Should have delegation receipts + the commitment
        commitment_receipts = [
            r for r in timeline if r.receipt_kind == ReceiptKind.COMMITMENT
        ]
        self.assertGreaterEqual(len(commitment_receipts), 1)

    def test_all_receipts_verifiable(self):
        ctx, contract, scopes, tool, agent = _setup()
        agent.buy(tool, item_id="book-1", quantity=2)
        agent.buy(tool, item_id="book-2", quantity=3)
        for r in ctx.receipts.timeline():
            self.assertTrue(r.verify_hash(), f"Receipt {r.receipt_id} failed verification")


if __name__ == "__main__":
    unittest.main()
