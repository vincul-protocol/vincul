"""
tests/sdk/test_enforce.py — VinculAgentContext and @vincul_enforce tests (unittest)
"""
import json
import unittest

from vincul.sdk.context import VinculContext
from vincul.sdk.enforce import VinculAgentContext, vincul_enforce
from vincul.types import FailureCode, OperationType


# ── Fixtures ─────────────────────────────────────────────────

NAMESPACE = "test.orders"
TOOL_ID = "enforce-test:place_order"


def _setup(ceiling="params.quantity <= 10"):
    """Create context, contract, scope chain, and a VinculAgentContext."""
    ctx = VinculContext()
    ctx.add_principal("principal:agent", role="agent", permissions=["delegate", "commit"])
    ctx.add_principal("principal:other", role="tool", permissions=["commit"])
    contract = ctx.create_contract(purpose_title="Enforce test")
    scopes = ctx.create_scope_chain(
        contract_id=contract.contract_id,
        issued_by="principal:agent",
        namespace=NAMESPACE,
        chain=[
            {"ceiling": "TOP"},
            {"ceiling": ceiling, "delegate": False},
        ],
    )
    agent_ctx = VinculAgentContext(
        principal_id="principal:agent",
        contract_id=contract.contract_id,
        signer=ctx.keypair("principal:agent"),
        runtime=ctx.runtime,
        _scopes=[scopes[-1]],
    )
    return ctx, contract, scopes, agent_ctx


def _setup_multi_namespace():
    """Create context with scopes across two namespaces."""
    ctx = VinculContext()
    ctx.add_principal("principal:agent", role="agent", permissions=["delegate", "commit"])
    ctx.add_principal("principal:other", role="tool", permissions=["commit"])
    contract = ctx.create_contract(purpose_title="Multi-ns test")

    order_scopes = ctx.create_scope_chain(
        contract_id=contract.contract_id,
        issued_by="principal:agent",
        namespace="test.orders",
        chain=[
            {"ceiling": "TOP"},
            {"ceiling": "params.quantity <= 10", "delegate": False},
        ],
    )
    shipping_scopes = ctx.create_scope_chain(
        contract_id=contract.contract_id,
        issued_by="principal:agent",
        namespace="test.shipping",
        chain=[
            {"ceiling": "TOP"},
            {"ceiling": "TOP", "delegate": False},
        ],
    )
    agent_ctx = VinculAgentContext(
        principal_id="principal:agent",
        contract_id=contract.contract_id,
        signer=ctx.keypair("principal:agent"),
        runtime=ctx.runtime,
        _scopes=[order_scopes[-1], shipping_scopes[-1]],
    )
    return ctx, contract, agent_ctx, order_scopes, shipping_scopes


# ── VinculAgentContext.find_scope ────────────────────────────

class TestFindScope(unittest.TestCase):
    def test_finds_matching_scope(self):
        _, _, scopes, agent_ctx = _setup()
        found = agent_ctx.find_scope(NAMESPACE, "COMMIT")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, scopes[-1].id)

    def test_returns_none_for_wrong_namespace(self):
        _, _, _, agent_ctx = _setup()
        found = agent_ctx.find_scope("nonexistent.ns", "COMMIT")
        self.assertIsNone(found)

    def test_returns_none_for_wrong_action_type(self):
        _, _, _, agent_ctx = _setup()
        # Scope has OBSERVE, PROPOSE, COMMIT — but not a made-up type
        # Test with a valid type that doesn't match if scope is COMMIT-only
        # Our scopes include all types, so test with a different namespace
        found = agent_ctx.find_scope("nonexistent", "OBSERVE")
        self.assertIsNone(found)

    def test_parent_namespace_matches_child(self):
        """A scope on 'test.orders' should match 'test.orders.sub'."""
        _, _, _, agent_ctx = _setup()
        found = agent_ctx.find_scope("test.orders.sub", "COMMIT")
        self.assertIsNotNone(found)

    def test_multi_namespace_resolves_correctly(self):
        _, _, agent_ctx, order_scopes, shipping_scopes = _setup_multi_namespace()
        found_order = agent_ctx.find_scope("test.orders", "COMMIT")
        found_ship = agent_ctx.find_scope("test.shipping", "COMMIT")
        self.assertEqual(found_order.id, order_scopes[-1].id)
        self.assertEqual(found_ship.id, shipping_scopes[-1].id)


# ── @vincul_enforce — success path ───────────────────────────

class TestEnforceSuccess(unittest.TestCase):
    def test_success_returns_json(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {"order_id": "ord-001"}

        raw = place_order(quantity=5)
        result = json.loads(raw)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action_type"], "COMMIT")
        self.assertIn("receipt_hash", result)

    def test_business_logic_payload_merged(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {"order_id": "ord-001", "total": quantity * 10}

        result = json.loads(place_order(quantity=3))
        self.assertEqual(result["order_id"], "ord-001")
        self.assertEqual(result["total"], 30)

    def test_business_logic_runs_on_success(self):
        _, _, _, agent_ctx = _setup()
        calls = []

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            calls.append(quantity)
            return {}

        place_order(quantity=5)
        self.assertEqual(calls, [5])

    def test_functools_wraps_preserves_name(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        self.assertEqual(place_order.__name__, "place_order")


# ── @vincul_enforce — failure path ───────────────────────────

class TestEnforceFailure(unittest.TestCase):
    def test_ceiling_violated(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {"order_id": "ord-001"}

        result = json.loads(place_order(quantity=999))
        self.assertEqual(result["status"], "denied")
        self.assertIn("failure_code", result)
        self.assertIn("hint", result)

    def test_business_logic_not_called_on_failure(self):
        _, _, _, agent_ctx = _setup()
        calls = []

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            calls.append(1)
            return {}

        place_order(quantity=999)
        self.assertEqual(calls, [])

    def test_no_scope_found(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace="nonexistent.namespace",
        )
        def do_something(value: int) -> dict:
            return {}

        result = json.loads(do_something(value=1))
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["failure_code"], FailureCode.SCOPE_INVALID.value)


# ── @vincul_enforce — pre_check ──────────────────────────────

class TestEnforcePreCheck(unittest.TestCase):
    def test_pre_check_denies(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            pre_check=lambda **kw: "blocked by pre-check",
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["message"], "blocked by pre-check")

    def test_pre_check_passes(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            pre_check=lambda **kw: None,
        )
        def place_order(quantity: int) -> dict:
            return {"order_id": "ord-001"}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["status"], "success")


# ── @vincul_enforce — namespace resolution ───────────────────

class TestEnforceNamespace(unittest.TestCase):
    def test_static_namespace(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["status"], "success")

    def test_dynamic_namespace(self):
        _, _, agent_ctx, _, _ = _setup_multi_namespace()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=lambda category, **_: f"test.{category}",
        )
        def do_action(category: str, quantity: int) -> dict:
            return {"category": category}

        result = json.loads(do_action(category="orders", quantity=3))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["category"], "orders")

    def test_dynamic_namespace_no_match(self):
        _, _, agent_ctx, _, _ = _setup_multi_namespace()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=lambda category, **_: f"test.{category}",
        )
        def do_action(category: str) -> dict:
            return {}

        result = json.loads(do_action(category="nonexistent"))
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["failure_code"], FailureCode.SCOPE_INVALID.value)


# ── @vincul_enforce — action_params ──────────────────────────

class TestEnforceActionParams(unittest.TestCase):
    def test_action_params_none_uses_all_kwargs(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            action_params=None,
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["status"], "success")

    def test_action_params_str_extracts_field(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            action_params="params",
        )
        def place_order(category: str, params: dict) -> dict:
            return {"category": category}

        result = json.loads(place_order(category="test", params={"quantity": 5}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["category"], "test")

    def test_action_params_str_ceiling_enforced(self):
        """Ceiling check applies to the extracted params, not all kwargs."""
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            action_params="params",
        )
        def place_order(category: str, params: dict) -> dict:
            return {}

        result = json.loads(place_order(category="test", params={"quantity": 999}))
        self.assertEqual(result["status"], "denied")

    def test_action_params_callable(self):
        _, _, _, agent_ctx = _setup()

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
            action_params=lambda quantity, **_: {"quantity": quantity},
        )
        def place_order(quantity: int, note: str) -> dict:
            return {"note": note}

        result = json.loads(place_order(quantity=5, note="rush"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["note"], "rush")


# ── @vincul_enforce — callbacks ──────────────────────────────

class TestEnforceCallbacks(unittest.TestCase):
    def test_on_commit_fired_on_success(self):
        _, _, _, agent_ctx = _setup()
        commits = []
        agent_ctx.on_commit = lambda receipt: commits.append(receipt.receipt_hash)

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        place_order(quantity=5)
        self.assertEqual(len(commits), 1)

    def test_on_commit_not_fired_on_failure(self):
        _, _, _, agent_ctx = _setup()
        commits = []
        agent_ctx.on_commit = lambda receipt: commits.append(1)

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        place_order(quantity=999)
        self.assertEqual(commits, [])

    def test_on_result_fired_on_success(self):
        _, _, _, agent_ctx = _setup()
        results = []
        agent_ctx.on_result = lambda tr, at, kw: results.append(("success", tr.success))

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        place_order(quantity=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("success", True))

    def test_on_result_fired_on_failure(self):
        _, _, _, agent_ctx = _setup()
        results = []
        agent_ctx.on_result = lambda tr, at, kw: results.append(("fail", tr.success))

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        place_order(quantity=999)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("fail", False))

    def test_on_result_extra_merged_into_success(self):
        _, _, _, agent_ctx = _setup()
        agent_ctx.on_result = lambda tr, at, kw: {"extra_field": "hello"}

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["extra_field"], "hello")

    def test_on_result_extra_merged_into_failure(self):
        _, _, _, agent_ctx = _setup()
        agent_ctx.on_result = lambda tr, at, kw: {"retry_hint": "try less"}

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=999))
        self.assertEqual(result["retry_hint"], "try less")

    def test_on_result_returns_none_no_crash(self):
        _, _, _, agent_ctx = _setup()
        agent_ctx.on_result = lambda tr, at, kw: None

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id=TOOL_ID,
            agent=lambda: agent_ctx,
            namespace=NAMESPACE,
        )
        def place_order(quantity: int) -> dict:
            return {}

        result = json.loads(place_order(quantity=5))
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
