"""
tests/sdk/test_decorators.py — @vincul_tool, @vincul_tool_action, ToolResult tests (unittest)
"""
import unittest

from vincul.identity import KeyPair
from vincul.runtime import VinculRuntime
from vincul.sdk.context import VinculContext
from vincul.sdk.decorators import ToolResult, vincul_tool_action, vincul_tool
from vincul.types import OperationType, ReceiptKind


# ── Fixtures ─────────────────────────────────────────────────

NAMESPACE = "test.orders"
TOOL_ID = "tool:Test:order-tool"
TOOL_VERSION = "1.0.0"


@vincul_tool(namespace=NAMESPACE, tool_id=TOOL_ID, tool_version=TOOL_VERSION)
class FakeTool:
    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime):
        self.key_pair = key_pair
        self.runtime = runtime
        self._call_count = 0

    @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="item_id")
    def place_order(self, *, item_id: str, quantity: int) -> dict:
        """Place a test order."""
        self._call_count += 1
        return {"order_id": f"ord-{self._call_count:04d}", "total": quantity * 10}

    @vincul_tool_action(action_type=OperationType.OBSERVE, side_effecting=False)
    def get_status(self, *, order_id: str) -> dict:
        return {"order_id": order_id, "status": "shipped"}


def _setup():
    """Create a VinculContext, contract, scope chain, and tool instance."""
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
            {"ceiling": "params.quantity <= 100"},
            {"ceiling": "params.quantity <= 10", "delegate": False},
        ],
    )
    tool = FakeTool(key_pair=ctx.keypair("vendor:B"), runtime=ctx.runtime)
    return ctx, contract, scopes, tool


# ── ToolResult ───────────────────────────────────────────────

class TestToolResult(unittest.TestCase):
    def test_success_properties(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.success)
        self.assertIsNone(result.failure_code)
        self.assertIsNone(result.message)

    def test_failure_properties(self):
        ctx, contract, scopes, tool = _setup()
        # quantity=999 exceeds ceiling (params.quantity <= 10)
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=999,
        )
        self.assertFalse(result.success)
        self.assertIsNotNone(result.failure_code)
        self.assertIsNotNone(result.message)

    def test_failure_code_none_on_success(self):
        tr = ToolResult(success=True, receipt=None, payload={"x": 1})
        self.assertIsNone(tr.failure_code)
        self.assertIsNone(tr.message)


# ── @vincul_tool class decorator ─────────────────────────────

class TestVinculToolDecorator(unittest.TestCase):
    def test_class_metadata(self):
        self.assertEqual(FakeTool._vincul_namespace, NAMESPACE)
        self.assertEqual(FakeTool._vincul_tool_id, TOOL_ID)
        self.assertEqual(FakeTool._vincul_tool_version, TOOL_VERSION)

    def test_tool_manifest_generated(self):
        ctx, contract, scopes, tool = _setup()
        m = tool.tool_manifest
        self.assertEqual(m["tool_id"], TOOL_ID)
        self.assertEqual(m["tool_version"], TOOL_VERSION)
        self.assertEqual(m["namespace"], NAMESPACE)
        self.assertEqual(m["tool_manifest_version"], "vmip-0.1")

    def test_manifest_vendor_id(self):
        ctx, contract, scopes, tool = _setup()
        self.assertEqual(tool.tool_manifest["vendor_id"], "vendor:B")

    def test_manifest_operations_collected(self):
        ctx, contract, scopes, tool = _setup()
        ops = tool.tool_manifest["operations"]
        op_names = [o["name"] for o in ops]
        self.assertIn("place_order", op_names)
        self.assertIn("get_status", op_names)

    def test_manifest_operation_action_types(self):
        ctx, contract, scopes, tool = _setup()
        ops = {o["name"]: o for o in tool.tool_manifest["operations"]}
        self.assertEqual(ops["place_order"]["action_type"], "COMMIT")
        self.assertEqual(ops["get_status"]["action_type"], "OBSERVE")

    def test_manifest_side_effecting_flags(self):
        ctx, contract, scopes, tool = _setup()
        ops = {o["name"]: o for o in tool.tool_manifest["operations"]}
        self.assertTrue(ops["place_order"]["side_effecting"])
        self.assertFalse(ops["get_status"]["side_effecting"])

    def test_manifest_attestation_policy(self):
        ctx, contract, scopes, tool = _setup()
        policy = tool.tool_manifest["attestation_policy"]
        self.assertTrue(policy["result_signature_required"])
        self.assertTrue(policy["external_ref_required"])

    def test_init_custom_state_preserved(self):
        ctx, contract, scopes, tool = _setup()
        self.assertEqual(tool._call_count, 0)


# ── @vincul_tool_action — success path ───────────────────────────

class TestToolOperationSuccess(unittest.TestCase):
    def test_success_result(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertTrue(result.success)

    def test_payload_returned(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertIsNotNone(result.payload)
        self.assertIn("order_id", result.payload)
        self.assertEqual(result.payload["total"], 20)

    def test_receipt_is_commitment(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertEqual(result.receipt.receipt_kind, ReceiptKind.COMMITMENT)
        self.assertTrue(result.receipt.verify_hash())

    def test_attested_result_present(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        ar = result.attested_result
        self.assertIsNotNone(ar)
        self.assertEqual(ar["status"], "success")
        self.assertEqual(ar["tool_id"], TOOL_ID)
        self.assertEqual(ar["result_version"], "vmip-0.1")

    def test_attested_result_hashes(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        ar = result.attested_result
        self.assertEqual(ar["contract_hash"], contract.descriptor_hash)
        self.assertEqual(ar["scope_hash"], scopes[2].descriptor_hash)
        self.assertEqual(ar["receipt_hash"], result.receipt.receipt_hash)

    def test_attested_result_signature(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        sig = result.attested_result["signature"]
        self.assertEqual(sig["signer_id"], "vendor:B")
        self.assertEqual(sig["algo"], "Ed25519")
        self.assertIsInstance(sig["sig"], str)

    def test_external_ref_auto_detected(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertIn("ord-", result.attested_result["external_ref"])

    def test_resource_key_in_action(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        # receipt detail should have resource = "place_order/book-1"
        self.assertIn("book-1", result.receipt.detail.get("resource", ""))

    def test_business_logic_executed(self):
        ctx, contract, scopes, tool = _setup()
        tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        self.assertEqual(tool._call_count, 1)

    def test_multiple_invocations(self):
        ctx, contract, scopes, tool = _setup()
        r1 = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=2,
        )
        r2 = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-2",
            quantity=3,
        )
        self.assertTrue(r1.success)
        self.assertTrue(r2.success)
        self.assertEqual(tool._call_count, 2)
        self.assertNotEqual(r1.receipt.receipt_hash, r2.receipt.receipt_hash)


# ── @vincul_tool_action — failure path ───────────────────────────

class TestToolOperationFailure(unittest.TestCase):
    def test_ceiling_violated(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=999,
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.payload)

    def test_failure_receipt_kind(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=999,
        )
        self.assertEqual(result.receipt.receipt_kind, ReceiptKind.FAILURE)
        self.assertTrue(result.receipt.verify_hash())

    def test_failure_attested_result(self):
        ctx, contract, scopes, tool = _setup()
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=999,
        )
        ar = result.attested_result
        self.assertIsNotNone(ar)
        self.assertEqual(ar["status"], "failure")

    def test_business_logic_not_executed_on_failure(self):
        ctx, contract, scopes, tool = _setup()
        tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=999,
        )
        self.assertEqual(tool._call_count, 0)

    def test_revoked_scope_fails(self):
        ctx, contract, scopes, tool = _setup()
        ctx.revoke_scope(
            scope_id=scopes[1].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:B",
        )
        result = tool.place_order(
            scope_id=scopes[2].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:A",
            item_id="book-1",
            quantity=1,
        )
        self.assertFalse(result.success)
        self.assertIn("REVOKED", result.failure_code or "")


# ── @vincul_tool_action metadata ─────────────────────────────────

class TestToolOperationMeta(unittest.TestCase):
    def test_op_meta_on_method(self):
        meta = FakeTool.place_order._vincul_op_meta
        self.assertEqual(meta["name"], "place_order")
        self.assertEqual(meta["action_type"], OperationType.COMMIT)
        self.assertTrue(meta["side_effecting"])

    def test_op_meta_observe(self):
        meta = FakeTool.get_status._vincul_op_meta
        self.assertEqual(meta["name"], "get_status")
        self.assertEqual(meta["action_type"], OperationType.OBSERVE)
        self.assertFalse(meta["side_effecting"])

    def test_op_meta_description_from_docstring(self):
        meta = FakeTool.place_order._vincul_op_meta
        self.assertIn("Place a test order", meta["description"])


if __name__ == "__main__":
    unittest.main()
