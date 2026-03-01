"""
tests/test_hashing.py — pact.hashing test suite (unittest)
"""
import math
import unittest

from pact.hashing import (
    jcs_serialize, pact_hash, pact_hash_constraint,
    normalize_contract, normalize_profile, normalize_ledger_balances,
    attestation_signature_message, is_valid_pact_hash, DOMAIN_PREFIXES,
)


class TestJCS(unittest.TestCase):
    def test_key_ordering(self):
        self.assertEqual(jcs_serialize({"z": 1, "a": 2, "m": 3}), b'{"a":2,"m":3,"z":1}')

    def test_nested_key_ordering(self):
        self.assertEqual(
            jcs_serialize({"b": {"z": 1, "a": 2}, "a": True}),
            b'{"a":true,"b":{"a":2,"z":1}}'
        )

    def test_null_false_zero(self):
        self.assertEqual(jcs_serialize({"x": None, "y": False, "z": 0}), b'{"x":null,"y":false,"z":0}')

    def test_boolean_not_int(self):
        self.assertEqual(jcs_serialize(True), b'true')
        self.assertEqual(jcs_serialize(False), b'false')
        self.assertEqual(jcs_serialize(1), b'1')

    def test_string_escaping_quote(self):
        self.assertEqual(jcs_serialize('a"b'), b'"a\\"b"')

    def test_string_escaping_newline(self):
        self.assertEqual(jcs_serialize('a\nb'), b'"a\\nb"')

    def test_string_escaping_backslash(self):
        self.assertEqual(jcs_serialize('a\\b'), b'"a\\\\b"')

    def test_string_escaping_control(self):
        self.assertEqual(jcs_serialize('\x01'), b'"\\u0001"')

    def test_empty_object(self):
        self.assertEqual(jcs_serialize({}), b'{}')

    def test_empty_list(self):
        self.assertEqual(jcs_serialize([]), b'[]')

    def test_list_preserves_order(self):
        self.assertEqual(jcs_serialize([3, 1, 2]), b'[3,1,2]')

    def test_null(self):
        self.assertEqual(jcs_serialize(None), b'null')

    def test_float_zero(self):
        self.assertEqual(jcs_serialize(0.0), b'0')

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            jcs_serialize(object())

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            jcs_serialize(math.nan)

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            jcs_serialize(math.inf)


class TestDomainPrefixes(unittest.TestCase):
    def test_all_prefixes_present(self):
        required = {"scope", "receipt", "contract", "constraint", "profile"}
        self.assertEqual(required, set(DOMAIN_PREFIXES.keys()))

    def test_all_null_terminated(self):
        for name, prefix in DOMAIN_PREFIXES.items():
            self.assertTrue(prefix.endswith("\x00"), f"{name} missing null terminator")

    def test_all_prefixes_unique(self):
        values = list(DOMAIN_PREFIXES.values())
        self.assertEqual(len(values), len(set(values)))

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            pact_hash("bogus_type", {})


SCOPE_FIXTURE = {
    "id": "00000000-0000-0000-0000-000000000001",
    "issued_by_scope_id": None, "issued_by": "principal:test",
    "issued_at": "2025-01-01T00:00:00Z", "expires_at": None,
    "domain": {"namespace": "test.resource", "types": ["OBSERVE"]},
    "predicate": "TOP", "ceiling": "TOP",
    "delegate": False, "revoke": "principal_only",
    "status": "active", "effective_at": None,
}


class TestKnownVectors(unittest.TestCase):
    def test_scope_hash(self):
        self.assertEqual(
            pact_hash("scope", SCOPE_FIXTURE),
            "07992bbbbbc3e34126643faa78673b7e8db889ee9ff968c1f72d9e1625e7dba0"
        )

    def test_constraint_top(self):
        self.assertEqual(
            pact_hash_constraint("TOP"),
            "98047c362cd87227ccb70ff1635ba9fb68de6f3af390b5cf7b866af2ede53f44"
        )

    def test_constraint_atom(self):
        self.assertEqual(
            pact_hash_constraint("action.params.duration_minutes <= 60"),
            "dd07ce67ec196e23cf6a5ba26ba54a7aab1b4dd484fe96d656bd774245a4563a"
        )


class TestNormalization(unittest.TestCase):
    def test_contract_principals_sorted(self):
        contract = {"principals": [
            {"principal_id": "z:peer", "role": "member"},
            {"principal_id": "a:owner", "role": "owner"},
        ]}
        result = normalize_contract(contract)
        self.assertEqual(result["principals"][0]["principal_id"], "a:owner")
        self.assertEqual(result["principals"][1]["principal_id"], "z:peer")

    def test_contract_normalization_does_not_mutate(self):
        contract = {"principals": [{"principal_id": "z:peer"}, {"principal_id": "a:owner"}]}
        original = [p["principal_id"] for p in contract["principals"]]
        normalize_contract(contract)
        self.assertEqual([p["principal_id"] for p in contract["principals"]], original)

    def test_contract_no_principals_ok(self):
        result = normalize_contract({"contract_id": "x"})
        self.assertEqual(result, {"contract_id": "x"})

    def test_profile_arrays_sorted(self):
        profile = {
            "supported_receipt_kinds": ["failure", "delegation", "commitment"],
            "supported_failure_codes": ["UNKNOWN", "SCOPE_REVOKED"],
            "signature_algorithms": ["Ed25519"],
        }
        result = normalize_profile(profile)
        self.assertEqual(result["supported_receipt_kinds"], ["commitment", "delegation", "failure"])
        self.assertEqual(result["supported_failure_codes"], ["SCOPE_REVOKED", "UNKNOWN"])

    def test_profile_null_attestation_schemas_ok(self):
        result = normalize_profile({"attestation_schemas": None})
        self.assertIsNone(result["attestation_schemas"])

    def test_profile_normalization_does_not_mutate(self):
        profile = {"supported_receipt_kinds": ["failure", "delegation"]}
        original = profile["supported_receipt_kinds"][:]
        normalize_profile(profile)
        self.assertEqual(profile["supported_receipt_kinds"], original)

    def test_ledger_balances_sorted_by_dimension(self):
        balances = [{"dimension": "USD"}, {"dimension": "GBP"}, {"dimension": "EUR"}]
        result = normalize_ledger_balances(balances)
        self.assertEqual([b["dimension"] for b in result], ["EUR", "GBP", "USD"])

    def test_ledger_normalization_does_not_mutate(self):
        balances = [{"dimension": "USD"}, {"dimension": "GBP"}]
        original = [b["dimension"] for b in balances]
        normalize_ledger_balances(balances)
        self.assertEqual([b["dimension"] for b in balances], original)


class TestDeterminism(unittest.TestCase):
    def test_same_payload_same_hash(self):
        payload = {"a": 1, "b": [1, 2, 3], "c": None}
        self.assertEqual(pact_hash("scope", payload), pact_hash("scope", payload))

    def test_different_payloads_different_hashes(self):
        self.assertNotEqual(pact_hash("scope", {"a": 1}), pact_hash("scope", {"a": 2}))

    def test_different_domains_different_hashes(self):
        payload = {"a": 1}
        self.assertNotEqual(pact_hash("scope", payload), pact_hash("receipt", payload))

    def test_key_order_irrelevant(self):
        h1 = pact_hash("scope", {"a": 1, "b": 2})
        h2 = pact_hash("scope", {"b": 2, "a": 1})
        self.assertEqual(h1, h2)


class TestAttestationMessage(unittest.TestCase):
    def test_structure(self):
        msg = attestation_signature_message("aabbcc", "ddeeff")
        self.assertTrue(msg.startswith(b"PACT_ATTEST_V1\x00"))
        self.assertIn(b"aabbcc", msg)
        self.assertIn(b"ddeeff", msg)

    def test_domain_separation(self):
        m1 = attestation_signature_message("hash_a", "hash_b")
        m2 = attestation_signature_message("hash_c", "hash_b")
        self.assertNotEqual(m1, m2)


class TestHashValidation(unittest.TestCase):
    def test_valid_hash(self):
        h = "07992bbbbbc3e34126643faa78673b7e8db889ee9ff968c1f72d9e1625e7dba0"
        self.assertTrue(is_valid_pact_hash(h))

    def test_uppercase_invalid(self):
        h = "07992BBBBBC3E34126643FAA78673B7E8DB889EE9FF968C1F72D9E1625E7DBA0"
        self.assertFalse(is_valid_pact_hash(h))

    def test_too_short(self):
        self.assertFalse(is_valid_pact_hash("abc123"))

    def test_none_invalid(self):
        self.assertFalse(is_valid_pact_hash(None))  # type: ignore


if __name__ == "__main__":
    unittest.main()
