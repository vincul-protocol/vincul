# Pact Protocol — Attestation
`spec/attestation/ATTEST.md` · Draft v0.2

---

## Purpose

An **Attestation Receipt** is a follow-on claim that a specific fingerprinted artifact corresponds to a specific Commitment Receipt.

Attestation closes the gap between what Pact records — a declared result under bounded authority — and what auditors need: evidence that the declared result corresponds to something that actually happened in an external system.

Pact does not prove external truth. It makes claims **attributable** and **fingerprint-verifiable**:

> Pact can make "what was claimed" verifiable and attributable.
> Whether the claim matches the world is outside the protocol,
> unless an external system chooses to participate.

This document defines the Attestation Receipt kind, its hashing and signature model, validation rules, and the policy hook for Coalition Contracts.

---

## 1. Design Principles

1. **Decoupled from execution** — Attestation is a separate Receipt linked to a Commitment; it is never embedded inline
2. **Retroactive** — An Attestation Receipt may be produced after the Commitment Receipt, within contract-defined time bounds
3. **Multi-signer capable** — Multiple parties may attest to the same Commitment; attestations are additive, not superseding
4. **Policy-driven** — Whether attestation is required, and who may attest, is defined by the Coalition Contract
5. **Honest about the oracle boundary** — Pact attests fingerprints, not external system state; cross-system proof requires external system participation and is out of scope

---

## 2. Attestation Receipt

### 2.1 Structure

An Attestation Receipt uses the standard Pact Receipt envelope (RECEIPT.md §2) with `receipt_kind: attestation` and the following kind-specific result:

```yaml
Receipt:
  receipt_id:    uuid
  receipt_kind:  "attestation"
  issued_at:     timestamp

  intent:
    action:        "attest"
    description:   string          # declarative statement of what is being attested
    initiated_by:  principal_id | agent_id

  authority:
    scope_id:      uuid
    scope_hash:    hash
    contract_id:   uuid
    contract_hash: hash
    signatories:   [principal_id | agent_id]

  result:
    outcome:  "success"
    detail:
      attests_receipt_id:    uuid   # receipt_id of the Commitment Receipt being attested
      attests_receipt_hash:  hash   # receipt_hash of the Commitment Receipt (MUST match)

      response_hash:
        algo:   "sha256"            # always sha256 in v0.2
        value:  hex_string          # SHA-256 of the canonicalized external response

      response_schema:  string      # opaque schema identifier; see §4
      external_ref:     string | null  # human-convenience duplicate of Commitment's external_ref

      produced_at:      timestamp   # when the attested artifact was produced (not when this Receipt was issued)

  prior_receipt:   uuid | null      # receipt_hash of prior Receipt in chain; typically the Commitment Receipt
  receipt_hash:    hash
  signatures:      [AttestationSignature]   # see §3; may be empty if contract policy does not require
```

### 2.2 Linkage invariant

An Attestation Receipt MUST reference exactly one Commitment Receipt via `attests_receipt_hash`. This value must equal the `receipt_hash` of the target Commitment Receipt exactly. Validators must verify this match before accepting the attestation.

An Attestation Receipt MUST NOT reference another Attestation Receipt. Attestations are claims about commitments, not chains of claims about claims.

### 2.3 Multiple attestations

Multiple Attestation Receipts may reference the same Commitment Receipt. This is permitted and expected in multi-party scenarios (e.g., the committing agent attests immediately; an independent witness attests after verifying the external response).

Multiple attestations are **additive**. No attestation supersedes another. No attestation invalidates another. Contract policy (§5) defines which attestations satisfy which requirements.

Validators must evaluate all attestations present and apply contract policy to determine whether the attestation requirement is satisfied. They must not stop at the first valid attestation.

---

## 3. Signature Model

### 3.1 Attestation signature message

Attestation signatures follow the detached model defined in HASHING.md §5, but with a distinct domain separation tag and a structured message covering both the commitment and the response fingerprint:

```
signature_message = "PACT_ATTEST_V1\x00" || attests_receipt_hash || response_hash.value
```

Where:
- `"PACT_ATTEST_V1\x00"` is the domain separation tag (UTF-8, null-byte delimited)
- `attests_receipt_hash` is the lowercase hex hash of the Commitment Receipt (UTF-8 encoded)
- `response_hash.value` is the lowercase hex SHA-256 of the canonicalized external response (UTF-8 encoded)
- `||` denotes byte concatenation

The signer signs this message directly. They do not sign `receipt_hash`. This is intentional: the attestation signature binds the commitment *and* the response fingerprint together. A valid attestation signature proves the signer attested to *this specific response* for *this specific commitment* — not merely that they signed the receipt envelope.

### 3.2 AttestationSignature structure

```yaml
AttestationSignature:
  signer_id:         principal_id | agent_id
  algo:              "Ed25519"                    # only valid value in v0.2
  signature_over:    string                       # the exact signature_message string (UTF-8)
  signature_bytes:   base64url_string
```

### 3.3 Signature verification

To verify an attestation signature:

1. Reconstruct `signature_message` from `attests_receipt_hash` and `response_hash.value`
2. Confirm `signature_over` in the AttestationSignature matches the reconstructed message
3. Verify `signature_bytes` against `signer_id`'s public key using the declared algorithm
4. Confirm `signer_id` is an acceptable attester under the contract's `attestation_policy` (§5)

Step 2 is required. A cryptographically valid signature whose `signature_over` does not match the reconstructed message is invalid.

### 3.3.1 Security considerations

The attestation signature attests only to the pair `(attests_receipt_hash, response_hash.value)`. It does not attest to envelope fields such as `issued_at`, `initiated_by`, `external_ref`, `description`, or any other metadata in the Attestation Receipt.

**Consequences validators must understand:**

- A valid attestation signature is portable across envelope metadata. A party could place a valid signature in a different Attestation Receipt envelope with different `issued_at` or `initiated_by` fields, and the signature would still verify. The *claim* (this response, for this commitment) remains true; the *envelope context* is unattested.
- Validators MUST verify `attests_receipt_hash` linkage to the target Commitment Receipt independently of signature validity. A valid signature does not substitute for linkage verification.
- Validators MUST treat envelope fields as informational unless those fields are separately covered by a signature over `receipt_hash`.
- Implementations that require envelope integrity — i.e., proof that the specific party named in `initiated_by` produced this specific envelope at this specific time — MAY require an additional signature over `receipt_hash` in addition to the attestation signature. This is a contract policy extension and a v0.3 candidate.

This design is intentional. The claim being made ("I attested to this response for this commitment") should be independently verifiable without trusting the envelope's provenance. Envelope integrity is a separate concern.

### 3.4 Unsigned attestations

An Attestation Receipt with an empty `signatures` block is structurally valid. It records a hash commitment without cryptographic attribution. Whether this satisfies contract requirements depends on the `attestation_policy` (§5).

Unsigned attestations provide (A)-level assurance only: anyone holding the original external response can verify the fingerprint matches. They do not provide (B)-level assurance of who made the claim.

---

## 4. Response Schema and Canonicalization

### 4.1 Schema identifiers

`response_schema` is an opaque string identifier that declares how the external response was canonicalized before hashing. Examples:

```
"stripe.payment_intent.v1"
"google.calendar.event.v3"
"pact.raw_bytes.v1"
```

`response_schema` is opaque to Pact core. The protocol does not interpret, validate, or require registration of schema identifiers. Implementations MAY publish canonicalization rules for specific schema IDs in external documentation or registries. No schema ID implies trust in a third party.

### 4.2 Canonicalization requirement

Whatever canonicalization rules apply to a given `response_schema`, they must be:

- **Deterministic** — the same external response always produces the same canonical bytes
- **Documented** — parties who need to verify the hash must be able to obtain the canonicalization rules for the schema ID used
- **Stable** — a schema ID's canonicalization rules must not change; breaking changes require a new schema ID (e.g., `stripe.payment_intent.v2`)

Pact does not enforce these properties. They are requirements on schema publishers. Implementations that use schema IDs with unstable canonicalization rules produce unverifiable attestations — this is an implementation error, not a protocol error.

### 4.3 Fallback: raw bytes

If no schema-specific canonicalization is available or appropriate, implementations SHOULD use `"pact.raw_bytes.v1"` which means: hash the exact response bytes as received, with no transformation. This is always reproducible by any party holding the original response, but may be fragile across serialization differences (e.g., JSON key ordering in API responses). Use with care.

### 4.4 What Pact verifies

Pact verifies:
- `response_hash.algo` is a recognized algorithm (`"sha256"` in v0.2)
- `response_hash.value` is a correctly formatted hex string of the expected length (64 hex chars for SHA-256)
- The signature (if present) is valid over the message defined in §3.1

Pact does not verify that `response_hash.value` corresponds to the declared `response_schema`. That verification requires the original external response and knowledge of the schema's canonicalization rules — which is exactly what external verifiers provide.

---

## 5. Coalition Contract Policy Hook

### 5.1 Attestation policy field

Coalition Contracts (COALITION.md) gain an optional `attestation_policy` field:

```yaml
attestation_policy:
  required_for_namespaces:  [string] | null   # if null, attestation is never required
  acceptable_attesters:     [AttesterRole]    # who may produce a valid attestation
  max_delay_seconds:        integer | null    # seconds after Commitment issued_at; null = no deadline
  require_signatures:       boolean           # if true, unsigned attestations never satisfy policy
```

Where `AttesterRole` is one of:

| Role | Meaning |
|---|---|
| `"initiator"` | The same identity that produced the Commitment Receipt |
| `"any_principal"` | Any principal listed in the contract |
| `"designated_witness"` | A principal with `role: "witness"` in the contract's principal list |
| `"any_signer"` | Any identity whose public key is known to the validator (most permissive) |

### 5.2 Policy evaluation

A set of Attestation Receipts satisfies the contract's attestation requirement for a given Commitment if:

1. At least one Attestation Receipt references the Commitment via `attests_receipt_hash`
2. That Receipt's `issued_at` is within `max_delay_seconds` of the Commitment's `issued_at` (if `max_delay_seconds` is non-null)
3. If `require_signatures: true`, at least one signature is present and valid
4. The signer (or the `initiated_by` identity for unsigned attestations) satisfies an `acceptable_attesters` role

All conditions must be satisfied. Validators must apply this check independently; no single attestation is self-declaring as "satisfying."

### 5.3 Attestation is optional in v0.2

If a contract does not include `attestation_policy`, attestation is not required. Commitment Receipts without corresponding Attestation Receipts are fully valid. The `attestation_policy` field exists to let contracts opt into stronger auditability — it is never mandatory at the protocol level.

---

## 6. Hashing

The `receipt_hash` for an Attestation Receipt is computed per HASHING.md §6.2:

```
receipt_hash = SHA-256( "PACT_RECEIPT_V1\x00" || JCS(receipt_without_hash_or_signatures) )
```

The `signatures` block is excluded from the hash input. The `attests_receipt_hash` and `response_hash.value` fields are included (they are part of `result.detail`).

---

## 7. Validation Summary

A validator presented with an Attestation Receipt may verify the following without external trust infrastructure:

| Check | What is verified | What is not verified |
|---|---|---|
| Structural validity | Receipt conforms to envelope schema | — |
| Linkage | `attests_receipt_hash` matches a real Commitment Receipt's `receipt_hash` | That the Commitment was legitimate |
| Hash format | `response_hash.value` is well-formed hex | That it matches the actual external response |
| Signature validity | Signature is valid over `PACT_ATTEST_V1\x00 \|\| attests_receipt_hash \|\| response_hash.value` | That the signer had correct information |
| Signer eligibility | Signer satisfies `acceptable_attesters` policy | That the signer is honest |
| Timing | `issued_at` is within `max_delay_seconds` of Commitment | — |

And independently, any party holding the original external response may:
1. Canonicalize it per the declared `response_schema`
2. SHA-256 hash the result
3. Compare to `response_hash.value`

A match proves the fingerprint is correct. It does not prove the external system state matches the commitment semantics — that requires trusting the external system's response integrity.

---

## 8. Out of Scope (v0.2)

| Excluded | Why |
|---|---|
| Cross-system proof (C) | Requires external system participation; cannot be mandated by Pact |
| Schema registry | Implementation and community concern; not a protocol concern |
| Batch attestation (one witness attests to N commitments) | Useful but adds complexity; reserved for v0.3. Likely structure: Merkle accumulator over commitment receipt hashes; signature over root hash; per-commitment inclusion proofs derivable from the tree. v0.2 designs must not preclude this. |
| Attestation revocation | An attestation is a past claim; revoking it requires a new model; deferred |
| Non-SHA-256 response hash algorithms | Algorithm agility deferred to v0.3 |

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | An Attestation Receipt references exactly one Commitment Receipt |
| 2 | `attests_receipt_hash` must equal the Commitment Receipt's `receipt_hash` exactly |
| 3 | An Attestation Receipt must not reference another Attestation Receipt |
| 4 | Multiple attestations for the same Commitment are permitted and additive |
| 5 | Attestation signatures are over `PACT_ATTEST_V1\x00 \|\| attests_receipt_hash \|\| response_hash.value` — not over `receipt_hash` |
| 6 | `response_schema` is opaque to Pact core; canonicalization rules live outside the protocol |
| 7 | Unsigned attestations are structurally valid; contract policy determines if they satisfy requirements |
| 8 | Attestation is opt-in; contracts without `attestation_policy` do not require it |
| 9 | Attestation policy is evaluated over the full set of attestations; validators must not stop at the first valid one |
| 10 | Pact attests fingerprints, not external system state |

---

## Appendix: Changes Required in Other Specs for v0.2

The following changes to existing specs are required alongside this document:

**RECEIPT.md:** Add `"attestation"` to the list of valid `receipt_kind` values (§3). Update the kinds table.

**COALITION.md:** Add `attestation_policy` as an optional field in the Coalition Contract schema (§2). Document its semantics (§5 of this doc). Add to the locked invariants.

**GOTCHAS.md:** Remove `external_ref is unverifiable` from the Known Gaps table and replace with a note: "Addressed by `spec/attestation/ATTEST.md` v0.2; implementations should migrate Commitment Receipt consumers to check for corresponding Attestation Receipts."

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
