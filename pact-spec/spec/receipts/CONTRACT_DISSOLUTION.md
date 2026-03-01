# Pact Protocol — Contract Dissolution Receipt
`spec/receipts/CONTRACT_DISSOLUTION.md` · Draft v0.2

---

## Purpose

In v0.1, contract dissolution was recorded by mutating the Coalition Contract object's `activation.status` and `activation.dissolved_at` fields, with a Failure Receipt as the only audit signal. This left dissolution as the only first-class protocol event without a first-class Receipt.

This document defines the `contract_dissolution` Receipt kind: a formal, hashable, attributable record produced exactly once when a contract transitions to `dissolved`.

This change is **additive and non-breaking**. The contract object's mutation semantics are unchanged. The `contract_dissolution` Receipt is the event complement to that mutation.

---

## 1. Design Principles

1. **One Receipt, one dissolution** — produced exactly once at the dissolution event; no second Receipt when downstream effects propagate
2. **Event, not condition** — dissolution is an explicit governance action; it gets an event Receipt (unlike expiry, which is a condition and does not)
3. **Self-contained** — carries both pre- and post-dissolution contract hashes so validators can anchor the event without live contract resolution
4. **Cascade is separate** — scope invalidation downstream of dissolution is handled by existing Revocation and Failure Receipt machinery; this Receipt records only the dissolution itself

---

## 2. Receipt Kind Definition

`receipt_kind: "contract_dissolution"`

### 2.1 Full structure

```yaml
Receipt:
  receipt_id:    uuid
  receipt_kind:  "contract_dissolution"
  issued_at:     timestamp                    # the moment dissolution is recorded

  intent:
    action:        "dissolve_contract"
    description:   string                     # declarative; e.g. "Coalition dissolved by unanimous decision"
    initiated_by:  principal_id | agent_id    # who triggered dissolution

  authority:
    scope_id:      null                        # MUST be null — this is a contract-level event
    scope_hash:    null                        # MUST be null
    contract_id:   uuid                        # MUST be present
    contract_hash: hash                        # hash of the contract at the moment before dissolution
    signatories:   [principal_id]             # principals whose signatures satisfy the governance rule

  result:
    outcome:  "success"
    detail:
      contract_id:          uuid
      contract_hash_before: hash              # descriptor_hash of contract with status: active
      contract_hash_after:  hash              # descriptor_hash of contract with status: dissolved + dissolved_at set
      dissolved_at:         timestamp         # the effective dissolution timestamp; = receipt issued_at for immediate dissolution
      dissolved_by:         principal_id | agent_id
      decision_rule:        "unanimous" | "majority" | "threshold"
      signatures_present:   integer           # count of qualifying signatures that satisfied the governance rule
      ledger_snapshot_hash: hash | null       # if contract policy required ledger_snapshot at dissolution (LEDGER.md §5.2)

  prior_receipt:   uuid | null
  receipt_hash:    hash
  signatures:      [AttestationSignature]     # must satisfy contract signatory_policy for dissolution (see §3)
```

### 2.2 `contract_hash_before` and `contract_hash_after`

The two hash fields serve different audit purposes:

- **`contract_hash_before`** — anchors this Receipt to the contract's active state; validators can verify the contract was valid immediately prior to dissolution
- **`contract_hash_after`** — anchors to the dissolved contract object; validators can verify the dissolution was correctly recorded

Both are required. A `contract_dissolution` Receipt with either field null is malformed.

The delta between the two hashes reflects exactly the change to `activation.status` (from `"active"` to `"dissolved"`) and `activation.dissolved_at` (from `null` to the dissolution timestamp). No other fields should differ. Implementations should verify this invariant.

---

## 3. Authority and Signature Requirements

### 3.1 Scope fields

`authority.scope_id` and `authority.scope_hash` MUST be `null`. Dissolution is a contract-level event, not scoped to any particular delegated authority.

### 3.2 Contract fields

`authority.contract_id` and `authority.contract_hash` MUST be present. `authority.contract_hash` MUST equal `result.detail.contract_hash_before`.

### 3.3 Signatories

`authority.signatories` MUST include the `principal_id` values of all principals whose signatures contributed to satisfying the governance `decision_rule`. This list must be sufficient to verify that the rule was met:

- `unanimous`: all principals listed in the contract
- `majority`: more than 50% of principals
- `threshold`: at least `governance.threshold` principals

The `signatures` block must contain valid signatures from each listed signatory per HASHING.md §5.

### 3.4 Signatory policy

The Coalition Contract's `signatory_policy` does not define a dissolution entry in v0.1. This is a v0.2 addition: the `signatory_policy` field in COALITION.md gains a `dissolution` entry:

```yaml
signatory_policy:
  dissolution:
    required_signers: ["principal"]    # all signatories satisfying the governance rule
```

Until COALITION.md is formally updated, the implicit rule is: all signatories whose signatures satisfy the `governance.decision_rule` must be present in the `signatures` block.

---

## 4. Timing and Uniqueness

### 4.1 Produced exactly once

A `contract_dissolution` Receipt is produced exactly once per contract, at the moment of dissolution. No second Receipt is produced when downstream effects propagate (scope invalidation, etc.).

### 4.2 Relationship to expiry

Expiry is a condition, not an event. No `contract_expiry` Receipt exists or is planned. The distinction is maintained:

| Cause | Receipt produced | How auditors detect it |
|---|---|---|
| Dissolution | `contract_dissolution` Receipt | Direct; first-class event |
| Expiry | None | Computed from `purpose.expires_at` + current time; emits `CONTRACT_EXPIRED` Failure Receipt on attempted use |

This asymmetry is intentional. Dissolution requires an explicit governance action that must be attributable; expiry is a time condition set at contract formation.

### 4.3 Relationship to Failure Receipts

After dissolution, any action attempted under the contract emits a `CONTRACT_DISSOLVED` Failure Receipt (FAILURE_CODES.md §2.2). The `contract_dissolution` Receipt records the dissolution event itself. Both are part of a complete audit record.

The `contract_dissolution` Receipt SHOULD appear in the receipt chain before any `CONTRACT_DISSOLVED` Failure Receipts, referenced via `prior_receipt`. This ordering makes the audit trail self-explanatory.

---

## 5. Ledger Snapshot at Dissolution

If the contract's `ledger_policy.snapshot_required_at_dissolution` is `true` (LEDGER.md §5):

- A `ledger_snapshot` Receipt MUST be produced for each scope with budget consumption before or simultaneously with the `contract_dissolution` Receipt
- The `contract_dissolution` Receipt's `result.detail.ledger_snapshot_hash` MUST be populated with the `receipt_hash` of the final snapshot (or a hash of multiple snapshots, if a batch mechanism is defined in v0.3)
- If ledger snapshots cannot be produced, a Failure Receipt with `LEDGER_SNAPSHOT_FAILED` must be emitted and dissolution must fail

If `snapshot_required_at_dissolution` is `false` or absent, `ledger_snapshot_hash` is `null`.

---

## 6. Hashing

The `receipt_hash` for a `contract_dissolution` Receipt is computed per HASHING.md §6.2:

```
receipt_hash = SHA-256( "PACT_RECEIPT_V1\x00" || JCS(receipt_without_hash_or_signatures) )
```

All fields including both `contract_hash_before` and `contract_hash_after` are part of the canonical payload. The `signatures` block is excluded.

---

## 7. Required Changes to Other Specs

### 7.1 RECEIPT.md §3 — Kinds table

Add `"contract_dissolution"` to the receipt kinds table:

| Kind | When produced |
|---|---|
| `contract_dissolution` | A Coalition Contract is dissolved under governance rules |

Update the introductory text of §3 from "v0.1 defines five Receipt kinds" to "v0.2 defines seven Receipt kinds" (adding `attestation` from ATTEST.md and `contract_dissolution` from this spec).

### 7.2 RECEIPT.md §7 — What Receipts Do Not Cover

Remove or update the entry:
> "Contract formation and dissolution — `spec/contract/COALITION.md`"

Replace with:
> "Contract dissolution Receipt kind — `spec/receipts/CONTRACT_DISSOLUTION.md` (v0.2)"
> "Contract formation — `spec/contract/COALITION.md` (not yet written)"

### 7.3 COALITION.md §5.4 — Dissolution

Replace the v0.1 note ("In v0.1, implementations SHOULD emit a Failure Receipt at the moment of dissolution as an audit signal") with:

> "In v0.2, implementations MUST emit a `contract_dissolution` Receipt at dissolution time, per `spec/receipts/CONTRACT_DISSOLUTION.md`. The v0.1 Failure Receipt fallback is superseded."

Add `dissolution` entry to `signatory_policy` schema per §3.4 of this document.

### 7.4 GOTCHAS.md — Known Gaps

Move `contract_dissolution Receipt kind not yet defined` from Open to Resolved:

> Resolved in v0.2 — `spec/receipts/CONTRACT_DISSOLUTION.md`. The `contract_dissolution` receipt kind is now a first-class event receipt. The v0.1 Failure Receipt fallback is superseded.

---

## 8. Non-Goals

This document does not specify:

- Contract formation receipts (deferred; no `contract_activation` or `contract_formation` kind in v0.2)
- Amendment receipts (contracts are immutable; amendments create new contracts)
- Multi-contract dissolution (each contract dissolves independently)
- Expiry events (expiry is a condition, not an event; no Receipt is defined or planned)

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | `contract_dissolution` is produced exactly once per contract, at dissolution time |
| 2 | `authority.scope_id` and `authority.scope_hash` MUST be null |
| 3 | `authority.contract_hash` MUST equal `result.detail.contract_hash_before` |
| 4 | Both `contract_hash_before` and `contract_hash_after` are required; neither may be null |
| 5 | The delta between before/after hashes reflects only `activation.status` and `activation.dissolved_at` changes |
| 6 | `authority.signatories` must satisfy the contract's `governance.decision_rule` |
| 7 | `contract_dissolution` is an event Receipt; expiry does not produce an equivalent Receipt |
| 8 | After dissolution, attempted actions emit `CONTRACT_DISSOLVED` Failure Receipts; the dissolution Receipt is not repeated |
| 9 | If `ledger_policy.snapshot_required_at_dissolution` is true, `ledger_snapshot_hash` must be populated |
| 10 | The `contract_dissolution` Receipt SHOULD appear in the chain before any downstream `CONTRACT_DISSOLVED` Failure Receipts |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
