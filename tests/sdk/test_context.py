"""
tests/sdk/test_context.py — VinculContext test suite (unittest)
"""
import unittest

from vincul.sdk.context import VinculContext
from vincul.types import OperationType, ScopeStatus


class TestAddPrincipal(unittest.TestCase):
    def test_returns_keypair(self):
        ctx = VinculContext()
        key = ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        self.assertEqual(key.principal_id, "vendor:A")

    def test_keypair_retrievable(self):
        ctx = VinculContext()
        key = ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        self.assertIs(ctx.keypair("vendor:A"), key)

    def test_keypair_not_found_raises(self):
        ctx = VinculContext()
        with self.assertRaises(KeyError):
            ctx.keypair("nonexistent")

    def test_multiple_principals(self):
        ctx = VinculContext()
        ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        ctx.add_principal("vendor:B", role="tool_provider", permissions=["commit"])
        self.assertNotEqual(
            ctx.keypair("vendor:A").principal_id,
            ctx.keypair("vendor:B").principal_id,
        )

    def test_principal_registered_in_registry(self):
        ctx = VinculContext()
        key = ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        found = ctx.registry.resolve("vendor:A")
        self.assertIsNotNone(found)


class TestCreateContract(unittest.TestCase):
    def _setup_ctx(self):
        ctx = VinculContext()
        ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        ctx.add_principal("vendor:B", role="tool_provider", permissions=["commit"])
        return ctx

    def test_returns_activated_contract(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(purpose_title="Test marketplace")
        self.assertTrue(contract.is_active())

    def test_contract_has_hash(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(purpose_title="Test marketplace")
        self.assertIsNotNone(contract.descriptor_hash)
        self.assertEqual(len(contract.descriptor_hash), 64)

    def test_contract_has_both_principals(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(purpose_title="Test marketplace")
        pids = contract.principal_ids()
        self.assertIn("vendor:A", pids)
        self.assertIn("vendor:B", pids)

    def test_contract_purpose_title(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(purpose_title="My title")
        self.assertEqual(contract.purpose["title"], "My title")

    def test_contract_stored_in_runtime(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(purpose_title="Test")
        stored = ctx.contracts.get(contract.contract_id)
        self.assertIsNotNone(stored)

    def test_custom_governance_rule(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(
            purpose_title="Test",
            governance_rule="majority",
        )
        self.assertEqual(contract.governance["decision_rule"], "majority")

    def test_custom_expires_at(self):
        ctx = self._setup_ctx()
        contract = ctx.create_contract(
            purpose_title="Test",
            expires_at="2030-06-01T00:00:00Z",
        )
        self.assertEqual(contract.purpose["expires_at"], "2030-06-01T00:00:00Z")

    def test_fewer_than_two_principals_raises(self):
        ctx = VinculContext()
        ctx.add_principal("vendor:A", role="agent_host", permissions=["commit"])
        with self.assertRaises(ValueError):
            ctx.create_contract(purpose_title="Test")


class TestCreateScopeChain(unittest.TestCase):
    def _setup_ctx_with_contract(self):
        ctx = VinculContext()
        ctx.add_principal("vendor:A", role="agent_host", permissions=["delegate", "commit"])
        ctx.add_principal("vendor:B", role="tool_provider", permissions=["delegate", "commit"])
        contract = ctx.create_contract(purpose_title="Test marketplace")
        return ctx, contract

    def test_returns_scope_list(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP"},
                {"ceiling": "params.quantity <= 10"},
                {"ceiling": "params.quantity <= 5", "delegate": False},
            ],
        )
        self.assertEqual(len(scopes), 3)

    def test_scopes_have_hashes(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP"}, {"ceiling": "TOP", "delegate": False}],
        )
        for s in scopes:
            self.assertIsNotNone(s.descriptor_hash)

    def test_root_has_no_parent(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP"}, {"ceiling": "TOP", "delegate": False}],
        )
        self.assertIsNone(scopes[0].issued_by_scope_id)

    def test_child_parent_linkage(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP"},
                {"ceiling": "TOP"},
                {"ceiling": "TOP", "delegate": False},
            ],
        )
        self.assertEqual(scopes[1].issued_by_scope_id, scopes[0].id)
        self.assertEqual(scopes[2].issued_by_scope_id, scopes[1].id)

    def test_last_scope_not_delegatable_by_default(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP"}, {"ceiling": "TOP"}],
        )
        self.assertTrue(scopes[0].delegate)
        self.assertFalse(scopes[1].delegate)

    def test_explicit_delegate_override(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP", "delegate": True},
                {"ceiling": "TOP", "delegate": True},
            ],
        )
        self.assertTrue(scopes[0].delegate)
        self.assertTrue(scopes[1].delegate)

    def test_namespace_propagated(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP", "delegate": False}],
        )
        self.assertEqual(scopes[0].domain.namespace, "marketplace.orders")

    def test_custom_operations(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            operations=(OperationType.OBSERVE, OperationType.PROPOSE),
            chain=[{"ceiling": "TOP", "delegate": False}],
        )
        self.assertEqual(scopes[0].domain.types, (OperationType.OBSERVE, OperationType.PROPOSE))

    def test_scopes_stored_in_runtime(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP", "delegate": False}],
        )
        for s in scopes:
            self.assertIsNotNone(ctx.scopes.get(s.id))

    def test_single_scope_chain(self):
        ctx, contract = self._setup_ctx_with_contract()
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[{"ceiling": "TOP"}],
        )
        self.assertEqual(len(scopes), 1)


class TestRevokeScope(unittest.TestCase):
    def _setup_full(self):
        ctx = VinculContext()
        ctx.add_principal("vendor:A", role="agent_host", permissions=["delegate", "commit"])
        ctx.add_principal("vendor:B", role="tool_provider", permissions=["delegate", "commit", "revoke"])
        contract = ctx.create_contract(purpose_title="Test")
        scopes = ctx.create_scope_chain(
            contract_id=contract.contract_id,
            issued_by="vendor:B",
            namespace="marketplace.orders",
            chain=[
                {"ceiling": "TOP"},
                {"ceiling": "TOP"},
                {"ceiling": "TOP", "delegate": False},
            ],
        )
        return ctx, contract, scopes

    def test_revoke_mid_cascades_to_leaf(self):
        ctx, contract, scopes = self._setup_full()
        ctx.revoke_scope(
            scope_id=scopes[1].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:B",
        )
        mid = ctx.scopes.get(scopes[1].id)
        leaf = ctx.scopes.get(scopes[2].id)
        self.assertEqual(mid.status, ScopeStatus.REVOKED)
        self.assertEqual(leaf.status, ScopeStatus.REVOKED)

    def test_revoke_does_not_affect_root(self):
        ctx, contract, scopes = self._setup_full()
        ctx.revoke_scope(
            scope_id=scopes[1].id,
            contract_id=contract.contract_id,
            initiated_by="vendor:B",
        )
        root = ctx.scopes.get(scopes[0].id)
        self.assertEqual(root.status, ScopeStatus.ACTIVE)


class TestConvenienceAccessors(unittest.TestCase):
    def test_receipts_accessor(self):
        ctx = VinculContext()
        self.assertIs(ctx.receipts, ctx.runtime.receipts)

    def test_scopes_accessor(self):
        ctx = VinculContext()
        self.assertIs(ctx.scopes, ctx.runtime.scopes)

    def test_contracts_accessor(self):
        ctx = VinculContext()
        self.assertIs(ctx.contracts, ctx.runtime.contracts)

    def test_custom_max_delegation_depth(self):
        ctx = VinculContext(max_delegation_depth=3)
        self.assertEqual(ctx.runtime.scopes._max_depth, 3)


if __name__ == "__main__":
    unittest.main()
