"""
tests/test_receipts.py — pact.receipts test suite (unittest)
"""
import unittest

from pact.receipts import (
    Receipt, ReceiptLog,
    delegation_receipt, commitment_receipt,
    failure_receipt, revocation_receipt, dissolution_receipt,
)
from pact.types import FailureCode, ReceiptKind

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
        r.initiated_by = "principal:attacker"
        self.assertFalse(r.verify_hash())

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
        log = ReceiptLog()
        r = make_commitment()
        r.initiated_by = "attacker"
        with self.assertRaises(ValueError):
            log.append(r)

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
