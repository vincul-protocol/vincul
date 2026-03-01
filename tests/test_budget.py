"""
Tests for pact.budget — Budget ledger
"""

import unittest
from decimal import Decimal

from pact.budget import BudgetLedger
from pact.types import FailureCode


SCOPE_A = "00000000-0000-0000-0000-00000000000a"
SCOPE_B = "00000000-0000-0000-0000-00000000000b"


class TestSetCeiling(unittest.TestCase):
    """Test ceiling registration."""

    def test_set_ceiling_basic(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("100.00"))

    def test_set_ceiling_integer_string(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "api_calls", "1000")
        self.assertEqual(ledger.get_balance(SCOPE_A, "api_calls"), Decimal("1000"))

    def test_set_ceiling_overwrite(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.set_ceiling(SCOPE_A, "GBP", "200.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("200.00"))

    def test_set_ceiling_multiple_dimensions(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.set_ceiling(SCOPE_A, "USD", "150.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("100.00"))
        self.assertEqual(ledger.get_balance(SCOPE_A, "USD"), Decimal("150.00"))

    def test_set_ceiling_multiple_scopes(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.set_ceiling(SCOPE_B, "GBP", "200.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("100.00"))
        self.assertEqual(ledger.get_balance(SCOPE_B, "GBP"), Decimal("200.00"))

    def test_set_ceiling_zero(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "0")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("0"))

    def test_set_ceiling_negative_rejected(self):
        ledger = BudgetLedger()
        with self.assertRaises(ValueError):
            ledger.set_ceiling(SCOPE_A, "GBP", "-10.00")

    def test_set_ceiling_invalid_string_rejected(self):
        ledger = BudgetLedger()
        with self.assertRaises(ValueError):
            ledger.set_ceiling(SCOPE_A, "GBP", "not_a_number")


class TestRecordDelta(unittest.TestCase):
    """Test consumption recording."""

    def test_record_delta_basic(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "9.99")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("90.01"))

    def test_record_delta_accumulates(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "10.00")
        ledger.record_delta(SCOPE_A, "GBP", "20.00")
        ledger.record_delta(SCOPE_A, "GBP", "30.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("40.00"))

    def test_record_delta_zero(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "0")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("100.00"))

    def test_record_delta_negative_rejected(self):
        ledger = BudgetLedger()
        with self.assertRaises(ValueError):
            ledger.record_delta(SCOPE_A, "GBP", "-5.00")

    def test_record_delta_invalid_string_rejected(self):
        ledger = BudgetLedger()
        with self.assertRaises(ValueError):
            ledger.record_delta(SCOPE_A, "GBP", "abc")

    def test_record_delta_without_ceiling(self):
        """Deltas can be recorded even without a ceiling."""
        ledger = BudgetLedger()
        ledger.record_delta(SCOPE_A, "GBP", "50.00")
        # No ceiling means get_balance returns None
        self.assertIsNone(ledger.get_balance(SCOPE_A, "GBP"))

    def test_record_delta_with_receipt_hash(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "10.00", receipt_hash="abc123")
        ledger.record_delta(SCOPE_A, "GBP", "20.00", receipt_hash="def456")
        snap = ledger.snapshot(SCOPE_A, "periodic")
        self.assertIn("abc123", snap["commitment_refs"])
        self.assertIn("def456", snap["commitment_refs"])

    def test_record_delta_precision(self):
        """Decimal arithmetic avoids float precision issues."""
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "0.30")
        ledger.record_delta(SCOPE_A, "GBP", "0.10")
        ledger.record_delta(SCOPE_A, "GBP", "0.10")
        ledger.record_delta(SCOPE_A, "GBP", "0.10")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("0.00"))


class TestGetBalance(unittest.TestCase):
    """Test balance queries."""

    def test_balance_unknown_scope_returns_none(self):
        ledger = BudgetLedger()
        self.assertIsNone(ledger.get_balance(SCOPE_A, "GBP"))

    def test_balance_unknown_dimension_returns_none(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        self.assertIsNone(ledger.get_balance(SCOPE_A, "USD"))

    def test_balance_after_consumption(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "25.50")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("74.50"))

    def test_balance_can_go_negative(self):
        """Balance can go negative if deltas exceed ceiling (overspend)."""
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "10.00")
        ledger.record_delta(SCOPE_A, "GBP", "15.00")
        self.assertEqual(ledger.get_balance(SCOPE_A, "GBP"), Decimal("-5.00"))


class TestCheckAvailable(unittest.TestCase):
    """Test the validator-facing availability check."""

    def test_no_ceiling_allows(self):
        ledger = BudgetLedger()
        result = ledger.check_available(SCOPE_A, "GBP", "999.99")
        self.assertTrue(result)

    def test_within_ceiling_allows(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        result = ledger.check_available(SCOPE_A, "GBP", "50.00")
        self.assertTrue(result)

    def test_exact_ceiling_allows(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        result = ledger.check_available(SCOPE_A, "GBP", "100.00")
        self.assertTrue(result)

    def test_exceeds_ceiling_denies(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        result = ledger.check_available(SCOPE_A, "GBP", "100.01")
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.BUDGET_EXCEEDED)

    def test_exceeds_after_consumption_denies(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "80.00")
        result = ledger.check_available(SCOPE_A, "GBP", "30.00")
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.BUDGET_EXCEEDED)

    def test_within_after_consumption_allows(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "80.00")
        result = ledger.check_available(SCOPE_A, "GBP", "20.00")
        self.assertTrue(result)

    def test_zero_amount_allows(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        result = ledger.check_available(SCOPE_A, "GBP", "0")
        self.assertTrue(result)

    def test_deny_detail_contains_info(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "90.00")
        result = ledger.check_available(SCOPE_A, "GBP", "20.00")
        self.assertFalse(result)
        self.assertEqual(result.detail["scope_id"], SCOPE_A)
        self.assertEqual(result.detail["dimension"], "GBP")
        self.assertEqual(result.detail["ceiling"], "100.00")
        self.assertEqual(result.detail["consumed"], "90.00")
        self.assertEqual(result.detail["remaining"], "10.00")

    def test_invalid_amount_denies(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        result = ledger.check_available(SCOPE_A, "GBP", "not_valid")
        self.assertFalse(result)
        self.assertEqual(result.failure_code, FailureCode.BUDGET_EXCEEDED)

    def test_independent_dimensions(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "50.00")
        ledger.set_ceiling(SCOPE_A, "USD", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "50.00")
        # GBP is exhausted
        self.assertFalse(ledger.check_available(SCOPE_A, "GBP", "0.01"))
        # USD is still available
        self.assertTrue(ledger.check_available(SCOPE_A, "USD", "50.00"))


class TestSnapshot(unittest.TestCase):
    """Test snapshot generation."""

    def test_snapshot_basic_structure(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "9.99", receipt_hash="ref001")

        snap = ledger.snapshot(
            SCOPE_A, "revocation",
            period_from="2025-01-01T00:00:00Z",
            period_to="2025-01-01T01:00:00Z",
        )

        self.assertEqual(snap["snapshot_type"], "revocation")
        self.assertEqual(snap["covers_scope_id"], SCOPE_A)
        self.assertEqual(snap["snapshot_period"]["from"], "2025-01-01T00:00:00Z")
        self.assertEqual(snap["snapshot_period"]["to"], "2025-01-01T01:00:00Z")
        self.assertIsNone(snap["prior_snapshot"])
        self.assertEqual(snap["commitment_refs"], ["ref001"])

    def test_snapshot_balances(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "9.99")

        snap = ledger.snapshot(SCOPE_A, "revocation")
        self.assertEqual(len(snap["balances"]), 1)
        bal = snap["balances"][0]
        self.assertEqual(bal["dimension"], "GBP")
        self.assertEqual(bal["ceiling"], 100.00)
        self.assertEqual(bal["consumed"], 9.99)
        self.assertEqual(bal["remaining"], 90.01)
        self.assertEqual(bal["commitment_count"], 0)  # no receipt_hash passed

    def test_snapshot_balances_sorted_by_dimension(self):
        """Balances are normalized: sorted by dimension."""
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "USD", "200.00")
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.set_ceiling(SCOPE_A, "EUR", "150.00")

        snap = ledger.snapshot(SCOPE_A, "periodic")
        dims = [b["dimension"] for b in snap["balances"]]
        self.assertEqual(dims, ["EUR", "GBP", "USD"])

    def test_snapshot_empty_scope(self):
        """Snapshot for a scope with no ceilings produces empty balances."""
        ledger = BudgetLedger()
        snap = ledger.snapshot(SCOPE_A, "on_demand")
        self.assertEqual(snap["balances"], [])
        self.assertEqual(snap["commitment_refs"], [])

    def test_snapshot_only_includes_target_scope(self):
        """Snapshot must not leak data from other scopes."""
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.set_ceiling(SCOPE_B, "GBP", "200.00")

        snap = ledger.snapshot(SCOPE_A, "periodic")
        self.assertEqual(len(snap["balances"]), 1)
        self.assertEqual(snap["balances"][0]["ceiling"], 100.00)

    def test_snapshot_types(self):
        """All four snapshot types are accepted."""
        ledger = BudgetLedger()
        for st in ("periodic", "revocation", "dissolution", "on_demand"):
            snap = ledger.snapshot(SCOPE_A, st)
            self.assertEqual(snap["snapshot_type"], st)

    def test_snapshot_commitment_refs_deduplicated_and_sorted(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        ledger.record_delta(SCOPE_A, "GBP", "10.00", receipt_hash="zzz")
        ledger.record_delta(SCOPE_A, "GBP", "10.00", receipt_hash="aaa")
        ledger.record_delta(SCOPE_A, "GBP", "10.00", receipt_hash="zzz")  # dupe

        snap = ledger.snapshot(SCOPE_A, "periodic")
        self.assertEqual(snap["commitment_refs"], ["aaa", "zzz"])

    def test_snapshot_period_defaults_to_none(self):
        ledger = BudgetLedger()
        snap = ledger.snapshot(SCOPE_A, "on_demand")
        self.assertIsNone(snap["snapshot_period"]["from"])
        self.assertIsNone(snap["snapshot_period"]["to"])


class TestDimensionsFor(unittest.TestCase):
    """Test the dimensions_for helper."""

    def test_no_dimensions(self):
        ledger = BudgetLedger()
        self.assertEqual(ledger.dimensions_for(SCOPE_A), [])

    def test_multiple_dimensions_sorted(self):
        ledger = BudgetLedger()
        ledger.set_ceiling(SCOPE_A, "USD", "200.00")
        ledger.set_ceiling(SCOPE_A, "GBP", "100.00")
        self.assertEqual(ledger.dimensions_for(SCOPE_A), ["GBP", "USD"])


class TestProtocolConformance(unittest.TestCase):
    """Verify BudgetLedger satisfies BudgetLedgerProtocol."""

    def test_isinstance_check(self):
        from pact.interfaces import BudgetLedgerProtocol
        ledger = BudgetLedger()
        self.assertIsInstance(ledger, BudgetLedgerProtocol)


if __name__ == "__main__":
    unittest.main()
