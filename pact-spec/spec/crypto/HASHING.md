# Pact Protocol — Hashing and Canonical Serialization
`spec/crypto/HASHING.md` · Draft v0.1

---

## Purpose

This document defines how Pact objects are canonically serialized and hashed to produce stable, verifiable identifiers: `descriptor_hash` for Scopes and Contracts, and `receipt_hash` for Receipts.

Hashing in Pact serves three functions:

1. **Tamper-evidence** — any modification to a hashed object produces a different hash
2. **Stable reference** — objects are referenced by hash across implementations without requiring live resolution
3. **Compliance testing** — two implementations presented with identical inputs must produce identical hashes

This document also defines the **detached signature model** — how cryptographic signatures relate to hashes without creating circular dependencies.

---

## 1. Design Principles

### 1.1 Versioned

Every hash is prefixed with a domain separation tag that encodes the object type and protocol version. This makes hash collisions across object types structurally impossible and makes algorithm upgrades non-breaking.

### 1.2 Domain-separated

Hashes for different object types are never interchangeable. A Scope hash and a Receipt hash with identical payloads will always differ due to domain prefix. This prevents cross-type confusion attacks.

### 1.3 Deterministic

Given the same object, any conformant implementation must produce the same hash. This requires a canonical serialization format with no implementation-defined ordering, whitespace, or encoding variation.

### 1.4 Agnostic to transport encoding

The canonical form used for hashing is independent of how objects are stored or transmitted. An object may be transmitted as CBOR and stored as MessagePack; it is always hashed via its JCS (JSON Canonicalization Scheme) form.

---

## 2. Canonical Serialization Format

Pact uses **JSON Canonicalization Scheme (JCS)** as defined in RFC 8785 as its canonical serialization format.

JCS provides:
- Deterministic key ordering (lexicographic, Unicode code point order)
- Deterministic number representation
- No insignificant whitespace
- UTF-8 encoding throughout
- Well-specified handling of all JSON scalar types

Implementations must use a JCS-conformant library or implement the RFC 8785 algorithm exactly. Deviation from JCS is a compliance violation.

### 2.1 Field inclusion rules

When producing the canonical payload for hashing:

- **Include:** all defined fields with their values, including null-valued optional fields
- **Exclude:** the hash field itself (`descriptor_hash`, `receipt_hash`)
- **Exclude:** the `signatures` block (see §5)
- **Exclude:** implementation-defined extension fields not defined in this spec

Optional fields with null values are included as `null` in the canonical form, not omitted. Omission and null are distinct and must not be conflated.

### 2.2 Timestamp serialization

All timestamps are serialized as **RFC 3339** strings in UTC, with second-level precision minimum and explicit `Z` suffix:

```
"2025-03-15T14:30:00Z"          # acceptable
"2025-03-15T14:30:00.000Z"      # acceptable (millisecond precision)
"2025-03-15T14:30:00+00:00"     # NOT acceptable (must use Z)
"2025-03-15T14:30:00"           # NOT acceptable (missing timezone)
```

### 2.3 Duration serialization

All durations are serialized as **ISO 8601 duration strings**:

```
"PT1H"        # 1 hour
"PT30M"       # 30 minutes
"P1DT12H"     # 1 day, 12 hours
```

### 2.4 Hash value serialization

Hash values embedded within objects (e.g., `scope_hash` inside a Receipt's authority block) are serialized as **lowercase hex strings** with no prefix:

```
"a3f1c9e2b4d07851..."    # correct
"0xa3f1c9e2b4d07851..."  # NOT correct (no 0x prefix)
"A3F1C9E2B4D07851..."    # NOT correct (must be lowercase)
```

### 2.5 UUIDs

All UUIDs are serialized as lowercase hyphenated strings per RFC 4122:

```
"f47ac10b-58cc-4372-a567-0e02b2c3d479"
```

### 2.6 ConstraintExpression serialization

`predicate` and `ceiling` fields (ConstraintExpression values) are serialized as their canonical DSL form as defined in `spec/dsl/CONSTRAINT.md §9`. The DSL canonical form is a string. It is embedded as a JSON string value.

---

## 3. Hash Algorithm

### 3.1 v0.1 default: SHA-256

Pact v0.1 uses **SHA-256** as its hash algorithm. SHA-256 produces a 32-byte (256-bit) digest.

SHA-256 is chosen for:
- Ubiquitous implementation availability
- Well-understood security properties
- Sufficient collision resistance for v0.1 threat model

### 3.2 Input to the hash function

The hash function input is:

```
DOMAIN_PREFIX_BYTES || JCS_CANONICAL_PAYLOAD_BYTES
```

Where `||` denotes byte concatenation. The domain prefix is prepended to the JCS payload before hashing. Both are UTF-8 encoded.

### 3.3 Output encoding

The hash output (raw bytes) is encoded as a **lowercase hex string** for storage and transmission.

---

## 4. Domain Separation Tags

Every object type has a unique domain separation prefix. The prefix is a UTF-8 string appended with a null byte (`\x00`) to delimit it from the payload:

| Object Type | Domain Prefix |
|---|---|
| Scope descriptor | `PACT_SCOPE_V1\x00` |
| Receipt | `PACT_RECEIPT_V1\x00` |
| Coalition Contract | `PACT_CONTRACT_V1\x00` |
| ConstraintExpression | `PACT_CONSTRAINT_V1\x00` |
| Compliance Profile | `PACT_PROFILE_V1\x00` |

The null byte delimiter ensures that a prefix that is a prefix of another prefix cannot produce identical inputs. (E.g., `PACT_SCOPE_V1` and `PACT_SCOPE_V10` would otherwise be ambiguous without the delimiter.)

### 4.1 Version upgrade path

When the protocol advances to v0.2 or v1.0, new domain prefixes are introduced (e.g., `PACT_SCOPE_V2\x00`). Old and new hashes are never interchangeable. Version negotiation is handled at the transport layer, not the hashing layer.

### 4.2 Computing a hash (pseudocode)

```
function pact_hash(object_type, canonical_payload_json):
  prefix = domain_prefix(object_type)          # e.g. "PACT_SCOPE_V1\x00"
  input  = utf8_encode(prefix) || utf8_encode(canonical_payload_json)
  digest = sha256(input)
  return hex_encode_lowercase(digest)
```

---

## 5. Detached Signature Model

Signatures in Pact are **detached** — they are not part of the hashed payload. This avoids circular dependency (where signatures would need to cover a hash that covers the signatures) and allows multiple parties to sign the same Receipt independently.

### 5.1 What is signed

A signature in Pact is always a signature **over the hash**, not over the raw payload:

```
signature_over = receipt_hash | descriptor_hash
signature_bytes = sign(private_key, utf8_encode(signature_over))
```

The signer signs the hash string (in its lowercase hex encoding, UTF-8 encoded). Not the payload. Not the JCS bytes.

### 5.2 Signatures block structure

The `signatures` block is attached to an object but excluded from its hash computation:

```yaml
signatures:
  - signer_id:           principal_id | agent_id
    signature_algorithm: "Ed25519"               # see §5.3
    signature_over:      "<receipt_hash_value>"  # the exact hash string being signed
    signature_bytes:     "<base64url-encoded signature>"
```

Multiple signatures may be present. Order within the signatures block is not canonical and is not hashed. Each signature is independently verifiable.

### 5.3 Signature algorithms (v0.1)

v0.1 supports one signature algorithm:

| Algorithm | Identifier | Key format |
|---|---|---|
| Ed25519 | `"Ed25519"` | 32-byte public key, base64url-encoded |

SHA-256 with RSA and ECDSA are explicitly excluded from v0.1. Algorithm agility is intentional but bounded. Implementations must reject signatures with unrecognized algorithm identifiers.

### 5.4 Signature verification

To verify a signature:

1. Recompute the hash from the canonical payload (the object without the `signatures` block)
2. Confirm `signature_over` matches the recomputed hash
3. Verify `signature_bytes` against `signer_id`'s public key using the declared algorithm

Step 2 is required. A signature where `signature_over` does not match the recomputed hash is invalid, even if the cryptographic verification succeeds.

### 5.5 What signatures are not

Signatures in Pact are **attestations**, not authorizations. A valid signature proves that a party attested to a hash at a point in time. It does not prove that the party had authority to authorize the underlying action. Authority is established by scope validity (SCHEMA.md), not by signature presence.

An object with no signatures is structurally valid if its hash is correct. Signature requirements are a contract-layer and implementation-layer concern, not a protocol invariant.

---

## 6. Object-Specific Hash Computation

### 6.1 Scope `descriptor_hash`

Fields included in canonical payload (all fields except `descriptor_hash`):

```
id, issued_by_scope_id, issued_by, issued_at, expires_at,
domain.namespace, domain.types,
predicate, ceiling,
delegate, revoke,
status, effective_at
```

Note: `status` is included. If status changes (e.g., from `active` to `pending_revocation`), the descriptor_hash changes. Implementations that cache scope hashes must invalidate the cache on status change.

> **Design note:** This means a Scope's hash is not stable across its lifecycle. Receipt `authority.scope_hash` captures the hash *at the time of the authorized action* — which is the semantically correct value for audit purposes.

### 6.2 Receipt `receipt_hash`

Fields included in canonical payload (all fields except `receipt_hash` and `signatures`):

```
receipt_id, receipt_kind, issued_at,
intent.action, intent.description, intent.initiated_by,
authority.scope_id, authority.scope_hash, authority.contract_id, authority.contract_hash, authority.signatories,
result.outcome, result.detail,
prior_receipt
```

`prior_receipt` is included. Chained receipts have hashes that encode their ancestry.

### 6.3 Coalition Contract `descriptor_hash`

Contract schema is not yet fully specified (`spec/contract/COALITION.md`). When that spec is written, the canonical field list will be defined there following the same rules. The domain prefix `PACT_CONTRACT_V1\x00` is reserved.

---

## 7. Compliance Test Vectors

The following test vectors allow implementations to verify their hashing is conformant. All values are produced by the reference implementation at `tools/test-vectors/generate.py` (v0.2).

**Note on contract hash change from v0.1:** The Coalition Contract hash changed between v0.1 and v0.2 because the v0.2 contract schema adds a `dissolution` entry to `signatory_policy`. This is expected — schema changes produce different hashes.

### 7.1 Object descriptor hashes

| Object | Domain prefix | Expected SHA-256 |
|---|---|---|
| Scope descriptor | `PACT_SCOPE_V1\x00` | `07992bbbbbc3e34126643faa78673b7e8db889ee9ff968c1f72d9e1625e7dba0` |
| Coalition Contract (active) | `PACT_CONTRACT_V1\x00` | `ea160e58b091116a5ecc87211265a1dafa1ae2f7fbc62d4ece6b706b798a9a08` |
| Coalition Contract (dissolved) | `PACT_CONTRACT_V1\x00` | `37809688c7636961fdb2a724e766aca88c5d2a46bd8db7860dcdfa7100e21fb6` |
| ConstraintExpression: `TOP` | `PACT_CONSTRAINT_V1\x00` | `98047c362cd87227ccb70ff1635ba9fb68de6f3af390b5cf7b866af2ede53f44` |
| ConstraintExpression: `action.params.duration_minutes <= 60` | `PACT_CONSTRAINT_V1\x00` | `dd07ce67ec196e23cf6a5ba26ba54a7aab1b4dd484fe96d656bd774245a4563a` |
| Compliance Profile: `pact-core-minimal-v0.2` | `PACT_PROFILE_V1\x00` | `62fb2a4c1ea65dc2d7ce911168ccfc7d1791af16ad0dce3555d09cbe5db9d27a` |

### 7.2 Receipt hashes (all v0.2 kinds)

All receipts use domain prefix `PACT_RECEIPT_V1\x00`.

| Receipt kind | Expected SHA-256 |
|---|---|
| `delegation` | `48f732e1d7a2a5c8a9a9195ab007f9e6dbef7dde21b3b4b482d785e66b9ed5d7` |
| `commitment` | `723ae93f0f84f7e79874662ea52aebcda01aeaa7ee6bdbd08731d5df275faa72` |
| `attestation` | `c3cd4ff294ce820f0cd25ba495ea29d32bbba77dc0621fdf0437afcce1c923b4` |
| `ledger_snapshot` | `55fcced73b910cc08c43a4898090c00ab32409833947b6396be3f48914307573` |
| `revocation` | `f36f7d210ec6aca062161a7f0f609498586888fc9d7f97ce25f05f9398fcedbb` |
| `contract_dissolution` | `97748e5f7a27d342f035ca996bfba15e349d1e4dd3107cd70c69c060d02cbb9e` |
| `failure` (SCOPE_REVOKED) | `da93e46a55e16f08395d3cc10477dcb3f784b9d88235778037d3a3bf5478722d` |

### 7.3 Attestation signature message fingerprint

The attestation signature message is `"PACT_ATTEST_V1\x00" || attests_receipt_hash || response_hash.value`. For the test vector receipt, the SHA-256 of the signature message bytes is:

`2507d323e5238ed8f527c470c55d503786859f1914d5f1acc69c32f8997d8f5e`

Implementations should verify they construct the signature message identically before signing or verifying.

### 7.4 JCS key ordering verification

| Input | Expected JCS output |
|---|---|
| `{"z":1,"a":2,"m":3}` | `{"a":2,"m":3,"z":1}` |
| `{"b":{"z":1,"a":2},"a":true}` | `{"a":true,"b":{"a":2,"z":1}}` |
| `{"x":null,"y":false,"z":0}` | `{"x":null,"y":false,"z":0}` |

### 7.5 Array normalization verification

Set-like arrays must be sorted before hashing:

| Array | Sort key | Example: input → sorted |
|---|---|---|
| Contract `principals` | `principal_id` ascending | `[{id:"z:peer"},{id:"a:owner"}]` → `[{id:"a:owner"},{id:"z:peer"}]` |
| Profile `supported_receipt_kinds` | string ascending | `["failure","delegation"]` → `["delegation","failure"]` |
| Ledger snapshot `balances` | `dimension` ascending | `[{dim:"USD"},{dim:"GBP"}]` → `[{dim:"GBP"},{dim:"USD"}]` |

## 8. What This Spec Does Not Cover

| Excluded | Where it lives |
|---|---|
| Key management and distribution | Implementation layer |
| Certificate infrastructure | Implementation layer |
| Signature requirements per receipt kind | `spec/contract/COALITION.md` |
| Algorithm negotiation between implementations | Transport layer |
| Hash versioning at the object level (per-field) | Out of scope for v0.1 |
| Merkle proofs over scope DAGs | `spec/audit/` (future) |

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | JCS (RFC 8785) is the canonical serialization format; no deviations are permitted |
| 2 | Hash input = domain prefix + `\x00` delimiter + JCS payload (UTF-8) |
| 3 | SHA-256 is the v0.1 hash algorithm |
| 4 | Hash output is lowercase hex; no prefix |
| 5 | `descriptor_hash` and `receipt_hash` are excluded from their own canonical payloads |
| 6 | `signatures` block is excluded from `receipt_hash` computation |
| 7 | Signatures are over the hash string, not the raw payload |
| 8 | Ed25519 is the only valid signature algorithm in v0.1 |
| 9 | Domain prefixes are versioned and null-byte-delimited |
| 10 | A valid signature does not imply authority; authority is established by scope validity |
| 11 | `status` is included in Scope canonical payload; scope hash changes on status change |
| 12 | Null optional fields are included as `null`, never omitted |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
