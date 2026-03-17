"""
tests/test_receipts.py — vincul.receipts test suite (unittest)
"""
import unittest
from dataclasses import FrozenInstanceError

from vincul.receipts import (
    Receipt, ReceiptLog,
    delegation_receipt, commitment_receipt,
    failure_receipt, revocation_receipt, dissolution_receipt,
    attestation_receipt, revert_attempt_receipt, ledger_snapshot_receipt,
)
from vincul.types import FailureCode, ReceiptKind

CONTRACT_ID = "00000000-0000-0000-0000-000000000003"
CONTRACT_HASH = "ea160e58b091116a5ecc87211265a1dafa1ae2f7fbc62d4ece6b706b798a9a08"
SCOPE_ID = "00000000-0000-0000-0000-000000000001"
SCOPE_HASH = "07992bbbbbc3e34126643faa78673b7e8db889ee9ff968c1f72d9e1625e7dba0"
PRINCIPAL = "principal:alice"

def make_commitment(resource="r:001"):
    return commitment_receipt(
        initiated_by=PRINCIPAL,
        scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
        contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
        namespace="test", resource=resource, params={},
        reversible=False, revert_window=None, external_ref=None,
    )


class TestReceiptHash(unittest.TestCase):
    def test_sealed_receipt_has_hash(self):
        r = make_commitment()
        self.assertIsNotNone(r.receipt_hash)
        self.assertEqual(len(r.receipt_hash), 64)

    def test_hash_verification_passes(self):
        self.assertTrue(make_commitment().verify_hash())

    def test_tampered_receipt_fails_verification(self):
        r = make_commitment()
        with self.assertRaises(FrozenInstanceError):
            r.initiated_by = "principal:attacker"

    def test_two_receipts_different_hashes(self):
        r1 = make_commitment()
        r2 = make_commitment()
        self.assertNotEqual(r1.receipt_hash, r2.receipt_hash)

    def test_unsealed_receipt_fails_verification(self):
        r = Receipt(
            receipt_id="x", receipt_kind=ReceiptKind.FAILURE,
            issued_at="2025-01-01T00:00:00Z",
            action="fail", description="d", initiated_by=PRINCIPAL,
            scope_id=None, scope_hash=None,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            signatories=[], outcome="failure", detail={},
        )
        self.assertFalse(r.verify_hash())


class TestReceiptKinds(unittest.TestCase):
    def test_delegation_kind(self):
        r = delegation_receipt(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            child_scope_id="child-001", child_scope_hash=SCOPE_HASH,
            parent_scope_id=SCOPE_ID, types_granted=["OBSERVE"],
            delegate_granted=False, revoke_granted="principal_only",
            expires_at=None, ceiling_hash=SCOPE_HASH,
        )
        self.assertEqual(r.receipt_kind, ReceiptKind.DELEGATION)
        self.assertEqual(r.outcome, "success")
        self.assertTrue(r.verify_hash())

    def test_failure_kind_and_code(self):
        r = failure_receipt(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            error_code=FailureCode.SCOPE_REVOKED,
            message="This scope was revoked.",
        )
        self.assertEqual(r.receipt_kind, ReceiptKind.FAILURE)
        self.assertEqual(r.outcome, "failure")
        self.assertEqual(r.detail["error_code"], "SCOPE_REVOKED")
        self.assertTrue(r.verify_hash())

    def test_revocation_kind(self):
        r = revocation_receipt(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            revocation_root=SCOPE_ID, authority_type="principal",
            effective_at="2025-01-01T01:00:00Z",
        )
        self.assertEqual(r.receipt_kind, ReceiptKind.REVOCATION)
        self.assertTrue(r.verify_hash())

    def test_dissolution_scope_fields_null(self):
        r = dissolution_receipt(
            initiated_by=PRINCIPAL,
            contract_id=CONTRACT_ID,
            contract_hash_before=CONTRACT_HASH,
            contract_hash_after="a" * 64,
            dissolved_at="2025-01-01T02:00:00Z",
            decision_rule="unanimous",
            signatures_present=2,
            signatories=[PRINCIPAL, "principal:bob"],
        )
        self.assertIsNone(r.scope_id)
        self.assertIsNone(r.scope_hash)
        self.assertTrue(r.verify_hash())


class TestAttestationReceipt(unittest.TestCase):
    def _make(self, **overrides):
        kwargs = dict(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            attests_receipt_id="commit-001",
            attests_receipt_hash="c" * 64,
            response_hash_algo="sha256",
            response_hash_value="d" * 64,
            response_schema="pact.raw_bytes.v1",
            external_ref="order-001",
            produced_at="2025-01-01T00:00:00Z",
        )
        kwargs.update(overrides)
        return attestation_receipt(**kwargs)

    def test_kind(self):
        r = self._make()
        self.assertEqual(r.receipt_kind, ReceiptKind.ATTESTATION)

    def test_action_is_attest(self):
        r = self._make()
        self.assertEqual(r.action, "attest")

    def test_sealed_and_verifiable(self):
        r = self._make()
        self.assertIsNotNone(r.receipt_hash)
        self.assertTrue(r.verify_hash())

    def test_detail_fields(self):
        r = self._make()
        self.assertEqual(r.detail["attests_receipt_id"], "commit-001")
        self.assertEqual(r.detail["attests_receipt_hash"], "c" * 64)
        self.assertEqual(r.detail["response_hash"]["algo"], "sha256")
        self.assertEqual(r.detail["response_hash"]["value"], "d" * 64)
        self.assertEqual(r.detail["response_schema"], "pact.raw_bytes.v1")
        self.assertEqual(r.detail["external_ref"], "order-001")
        self.assertEqual(r.detail["produced_at"], "2025-01-01T00:00:00Z")

    def test_null_external_ref(self):
        r = self._make(external_ref=None)
        self.assertIsNone(r.detail["external_ref"])
        self.assertTrue(r.verify_hash())

    def test_prior_receipt_linkage(self):
        r = self._make(prior_receipt="e" * 64)
        self.assertEqual(r.prior_receipt, "e" * 64)
        self.assertTrue(r.verify_hash())

    def test_round_trip(self):
        original = self._make()
        restored = Receipt.from_dict(original.to_dict())
        self.assertEqual(restored.receipt_hash, original.receipt_hash)
        self.assertTrue(restored.verify_hash())

    def test_custom_description(self):
        r = self._make(description="Custom attestation note")
        self.assertEqual(r.description, "Custom attestation note")

    def test_default_description(self):
        r = self._make()
        self.assertIn("commit-001", r.description)


class TestRevertAttemptReceipt(unittest.TestCase):
    def _make(self, **overrides):
        kwargs = dict(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            target_commitment="commit-001",
            triggered_by="revoke-001",
            revert_detail="Cancelled booking XYZ",
        )
        kwargs.update(overrides)
        return revert_attempt_receipt(**kwargs)

    def test_kind(self):
        r = self._make()
        self.assertEqual(r.receipt_kind, ReceiptKind.REVERT_ATTEMPT)

    def test_action_is_revert(self):
        r = self._make()
        self.assertEqual(r.action, "revert")

    def test_sealed_and_verifiable(self):
        r = self._make()
        self.assertIsNotNone(r.receipt_hash)
        self.assertTrue(r.verify_hash())

    def test_detail_fields(self):
        r = self._make()
        self.assertEqual(r.detail["target_commitment"], "commit-001")
        self.assertEqual(r.detail["triggered_by"], "revoke-001")
        self.assertEqual(r.detail["revert_detail"], "Cancelled booking XYZ")
        self.assertIsNone(r.detail["residual"])

    def test_success_outcome(self):
        r = self._make(outcome="success")
        self.assertEqual(r.outcome, "success")

    def test_failure_outcome(self):
        r = self._make(outcome="failure")
        self.assertEqual(r.outcome, "failure")
        self.assertTrue(r.verify_hash())

    def test_partial_outcome_with_residual(self):
        r = self._make(outcome="partial", residual="Could not cancel hotel")
        self.assertEqual(r.outcome, "partial")
        self.assertEqual(r.detail["residual"], "Could not cancel hotel")
        self.assertTrue(r.verify_hash())

    def test_prior_receipt_linkage(self):
        r = self._make(prior_receipt="f" * 64)
        self.assertEqual(r.prior_receipt, "f" * 64)
        self.assertTrue(r.verify_hash())

    def test_round_trip(self):
        original = self._make()
        restored = Receipt.from_dict(original.to_dict())
        self.assertEqual(restored.receipt_hash, original.receipt_hash)
        self.assertTrue(restored.verify_hash())

    def test_default_description(self):
        r = self._make()
        self.assertIn("commit-001", r.description)


class TestLedgerSnapshotReceipt(unittest.TestCase):
    BALANCES = [
        {"dimension": "USD", "ceiling": "100.00", "consumed": "42.50",
         "remaining": "57.50", "commitment_count": 3},
        {"dimension": "GBP", "ceiling": "80.00", "consumed": "10.00",
         "remaining": "70.00", "commitment_count": 1},
    ]

    def _make(self, **overrides):
        kwargs = dict(
            initiated_by=PRINCIPAL,
            scope_id=SCOPE_ID, scope_hash=SCOPE_HASH,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            snapshot_type="revocation",
            covers_scope_id=SCOPE_ID,
            snapshot_from="2025-01-01T00:00:00Z",
            snapshot_to="2025-01-02T00:00:00Z",
            balances=self.BALANCES,
        )
        kwargs.update(overrides)
        return ledger_snapshot_receipt(**kwargs)

    def test_kind(self):
        r = self._make()
        self.assertEqual(r.receipt_kind, ReceiptKind.LEDGER_SNAPSHOT)

    def test_action_is_ledger_snapshot(self):
        r = self._make()
        self.assertEqual(r.action, "ledger_snapshot")

    def test_sealed_and_verifiable(self):
        r = self._make()
        self.assertIsNotNone(r.receipt_hash)
        self.assertTrue(r.verify_hash())

    def test_detail_fields(self):
        r = self._make()
        self.assertEqual(r.detail["snapshot_type"], "revocation")
        self.assertEqual(r.detail["covers_scope_id"], SCOPE_ID)
        self.assertEqual(r.detail["snapshot_period"]["from"], "2025-01-01T00:00:00Z")
        self.assertEqual(r.detail["snapshot_period"]["to"], "2025-01-02T00:00:00Z")
        self.assertEqual(len(r.detail["balances"]), 2)

    def test_snapshot_types(self):
        for stype in ("periodic", "revocation", "dissolution", "on_demand"):
            r = self._make(snapshot_type=stype)
            self.assertEqual(r.detail["snapshot_type"], stype)
            self.assertTrue(r.verify_hash())

    def test_null_prior_snapshot(self):
        r = self._make(prior_snapshot=None)
        self.assertIsNone(r.detail["prior_snapshot"])
        self.assertTrue(r.verify_hash())

    def test_with_prior_snapshot(self):
        r = self._make(prior_snapshot="a" * 64)
        self.assertEqual(r.detail["prior_snapshot"], "a" * 64)
        self.assertTrue(r.verify_hash())

    def test_null_commitment_refs(self):
        r = self._make(commitment_refs=None)
        self.assertIsNone(r.detail["commitment_refs"])
        self.assertTrue(r.verify_hash())

    def test_with_commitment_refs(self):
        refs = ["b" * 64, "c" * 64]
        r = self._make(commitment_refs=refs)
        self.assertEqual(r.detail["commitment_refs"], refs)
        self.assertTrue(r.verify_hash())

    def test_prior_receipt_linkage(self):
        r = self._make(prior_receipt="d" * 64)
        self.assertEqual(r.prior_receipt, "d" * 64)
        self.assertTrue(r.verify_hash())

    def test_round_trip(self):
        original = self._make()
        restored = Receipt.from_dict(original.to_dict())
        self.assertEqual(restored.receipt_hash, original.receipt_hash)
        self.assertTrue(restored.verify_hash())

    def test_default_description(self):
        r = self._make()
        self.assertIn("revocation", r.description)
        self.assertIn(SCOPE_ID, r.description)

    def test_empty_balances(self):
        r = self._make(balances=[])
        self.assertEqual(r.detail["balances"], [])
        self.assertTrue(r.verify_hash())


class TestReceiptFrozen(unittest.TestCase):
    def test_cannot_mutate_after_seal(self):
        r = make_commitment()
        with self.assertRaises(FrozenInstanceError):
            r.outcome = "failure"

    def test_cannot_mutate_receipt_hash(self):
        r = make_commitment()
        with self.assertRaises(FrozenInstanceError):
            r.receipt_hash = "a" * 64

    def test_cannot_mutate_contract_id(self):
        r = make_commitment()
        with self.assertRaises(FrozenInstanceError):
            r.contract_id = "other"

    def test_seal_twice_raises(self):
        r = make_commitment()  # already sealed by builder
        with self.assertRaises(RuntimeError) as ctx:
            r.seal()
        self.assertIn("already sealed", str(ctx.exception))



class TestSerialization(unittest.TestCase):
    def test_round_trip(self):
        original = make_commitment()
        restored = Receipt.from_dict(original.to_dict())
        self.assertEqual(restored.receipt_hash, original.receipt_hash)
        self.assertEqual(restored.receipt_kind, original.receipt_kind)
        self.assertTrue(restored.verify_hash())


class TestReceiptLog(unittest.TestCase):
    def test_append_and_get(self):
        log = ReceiptLog()
        r = make_commitment()
        log.append(r)
        self.assertIs(log.get(r.receipt_hash), r)

    def test_append_order_preserved(self):
        log = ReceiptLog()
        r1 = make_commitment("r:001")
        r2 = make_commitment("r:002")
        r3 = make_commitment("r:003")
        for r in [r1, r2, r3]:
            log.append(r)
        resources = [r.detail["resource"] for r in log.timeline()]
        self.assertEqual(resources, ["r:001", "r:002", "r:003"])

    def test_duplicate_rejected(self):
        log = ReceiptLog()
        r = make_commitment()
        log.append(r)
        with self.assertRaises(ValueError):
            log.append(r)

    def test_tampered_receipt_rejected(self):
        r = make_commitment()
        with self.assertRaises(FrozenInstanceError):
            r.initiated_by = "attacker"

    def test_unsealed_receipt_rejected(self):
        log = ReceiptLog()
        r = Receipt(
            receipt_id="x", receipt_kind=ReceiptKind.FAILURE,
            issued_at="2025-01-01T00:00:00Z",
            action="fail", description="d", initiated_by=PRINCIPAL,
            scope_id=None, scope_hash=None,
            contract_id=CONTRACT_ID, contract_hash=CONTRACT_HASH,
            signatories=[], outcome="failure", detail={},
        )
        with self.assertRaises(ValueError):
            log.append(r)

    def test_for_contract_query(self):
        log = ReceiptLog()
        log.append(make_commitment("r:001"))
        log.append(make_commitment("r:002"))
        self.assertEqual(len(log.for_contract(CONTRACT_ID)), 2)

    def test_for_scope_query(self):
        log = ReceiptLog()
        log.append(make_commitment())
        self.assertEqual(len(log.for_scope(SCOPE_ID)), 1)
        self.assertEqual(len(log.for_scope("other")), 0)

    def test_len(self):
        log = ReceiptLog()
        self.assertEqual(len(log), 0)
        log.append(make_commitment("r:001"))
        log.append(make_commitment("r:002"))
        self.assertEqual(len(log), 2)


if __name__ == "__main__":
    unittest.main()
