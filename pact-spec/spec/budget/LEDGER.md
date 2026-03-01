# Pact Protocol — Budget Ledger
`spec/budget/LEDGER.md` · Draft v0.2

---

## Purpose

This document defines how Pact models budget consumption — the tracking of cumulative resource usage against the `BudgetAtom` ceilings declared in Scope predicates and ceilings.

Pact's position on budget accounting is **honest and bounded**:

> Pact can bound authority to consume resources deterministically.
> Pact does not guarantee global spend accounting consistency across
> implementations unless Ledger Snapshot Receipts are used.

This is not a weakness. It is the correct infrastructure cut. Budget arithmetic, currency rounding, concurrency ordering, and settlement are implementation-layer concerns. Pact's job is to ensure that the *authority* to consume is structurally bounded and that consumption is *attributable* — not to act as a settlement layer.

---

## 1. Design Principles

1. **Ledger is parallel state** — the authoritative ledger is maintained by each implementation; receipts declare deltas, not reconstruct totals
2. **Snapshots are the audit bridge** — optional Ledger Snapshot Receipts make accumulated state portable and hashable at points in time
3. **Revocation-time snapshots are policy-driven** — contracts may require a snapshot at revocation; this is the primary cross-implementation audit point
4. **No global ordering required** — the protocol does not impose ordering semantics on concurrent budget consumers; implementations must handle concurrency locally
5. **No currency arithmetic in the protocol** — rounding rules, exchange rates, and multi-currency reconciliation are outside Pact core

---

## 2. Budget Dimensions

A budget dimension is a named, typed quantity that a scope may consume. Dimensions are declared in the Coalition Contract's `budget_policy.dimensions` field (COALITION.md §8).

### 2.1 Dimension structure

```yaml
BudgetDimension:
  name:       string      # e.g. "GBP", "USD", "api_calls", "energy_kwh"
  unit:       string      # human-readable unit label; not interpreted by protocol
  precision:  integer     # decimal places for this dimension; e.g. 2 for currency
```

Dimension names are case-sensitive. `"GBP"` and `"gbp"` are distinct dimensions. Implementations must treat names as opaque strings; the protocol does not interpret currency codes or unit semantics.

### 2.2 Precision

`precision` defines the number of decimal places used when recording consumption and ceiling values for this dimension. All values for a given dimension must be expressed at this precision in receipts and snapshots.

Rounding rules when a computed value exceeds the declared precision are implementation-defined. The protocol requires only that the precision declaration exists and is applied consistently by a single implementation. Cross-implementation consistency requires snapshot comparison.

---

## 3. Budget Delta on Commitment Receipts

When a `COMMIT`-type action consumes budget, the Commitment Receipt's `result.detail` gains a `budget_consumed` block:

```yaml
budget_consumed:
  - dimension:    string           # must match a dimension in contract's budget_policy.dimensions
    delta:        decimal          # positive value consumed by this action, at declared precision
    ledger_ref:   hash | null      # hash of the most recent Ledger Snapshot this delta is applied against
                                   # null if no snapshot exists yet for this scope
    running_total: decimal | null  # implementation's running total after this delta; informational only
```

### 3.1 `ledger_ref`

`ledger_ref` is a hash pointer to the most recent Ledger Snapshot Receipt for this scope and dimension, as of the time the action was committed. It is:

- **Recommended** when a prior snapshot exists — it anchors the delta to a known baseline
- **null** when no snapshot has been produced yet (e.g., first consumption action under a scope)
- **Not required** — a Commitment Receipt without `ledger_ref` is structurally valid; the delta is still recorded

`ledger_ref` enables partial audit: a validator holding the referenced snapshot and all subsequent Commitment Receipts can reconstruct the ledger state up to any point, without requiring the full history from scope issuance.

### 3.2 `running_total`

`running_total` is the implementation's asserted accumulated consumption for this scope and dimension after applying this delta. It is:

- **Informational only** — it is not a protocol invariant
- **Not verified** by other implementations
- Useful for debugging and dashboards

Validators must not treat `running_total` as authoritative. The authoritative total is computed from snapshots and deltas.

---

## 4. Ledger Snapshot Receipt

A **Ledger Snapshot Receipt** is a new optional receipt kind (`receipt_kind: "ledger_snapshot"`) that records the accumulated budget state for a scope at a point in time, in a hashable, portable form.

### 4.1 Structure

```yaml
Receipt:
  receipt_id:    uuid
  receipt_kind:  "ledger_snapshot"
  issued_at:     timestamp

  intent:
    action:        "ledger_snapshot"
    description:   string
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
      snapshot_type:    "periodic" | "revocation" | "dissolution" | "on_demand"
      covers_scope_id:  uuid               # the scope this snapshot covers
      snapshot_period:
        from:           timestamp          # start of period covered (inclusive)
        to:             timestamp          # end of period covered (inclusive); = issued_at for live snapshot
      balances:
        - dimension:     string
          ceiling:       decimal           # the scope's ceiling for this dimension
          consumed:      decimal           # total consumed within snapshot period, at declared precision
          remaining:     decimal           # ceiling - consumed; informational
          commitment_count: integer        # number of Commitment Receipts included in this total
      prior_snapshot:   uuid | null        # receipt_hash of previous snapshot for this scope, if any
      commitment_refs:  [uuid] | null      # receipt_hashes of Commitment Receipts included in this total
                                           # SHOULD be populated for revocation and dissolution snapshots
                                           # MAY be omitted for periodic snapshots (use prior_snapshot chain)

  prior_receipt:   uuid | null
  receipt_hash:    hash
  signatures:      [AttestationSignature]
```

### 4.2 Snapshot types

| Type | When produced | `commitment_refs` |
|---|---|---|
| `periodic` | On a schedule defined by contract policy | Optional |
| `revocation` | At scope revocation time, if contract policy requires | SHOULD be populated |
| `dissolution` | At contract dissolution time, if contract policy requires | SHOULD be populated |
| `on_demand` | Explicitly requested by an authorized principal | Optional |

### 4.3 Snapshot hash

The `receipt_hash` for a Ledger Snapshot Receipt is computed per HASHING.md §6.2 using domain prefix `PACT_RECEIPT_V1\x00`. The `balances` array is included in the canonical payload, sorted by `dimension` ascending (Unicode code point order) — same normalization rule as `principals` in Coalition Contracts.

### 4.4 What snapshots enable

A validator holding:
- A Ledger Snapshot Receipt at time T₁
- All Commitment Receipts with `ledger_ref` pointing to that snapshot (or issued after T₁)

Can compute:
- Total consumption from T₁ to any subsequent point T₂
- Whether the ceiling was exceeded at any point in [T₁, T₂]
- Attribution of each delta to a specific Commitment Receipt and its `initiated_by`

A validator without any snapshot must rely on the full Commitment Receipt history from scope issuance — which may not be available across implementations.

---

## 5. Coalition Contract Policy Hook

Coalition Contracts gain an optional `ledger_policy` field:

```yaml
ledger_policy:
  snapshot_required_at_revocation:   boolean    # if true, revocation MUST include a ledger_snapshot receipt
  snapshot_required_at_dissolution:  boolean    # if true, dissolution MUST include a ledger_snapshot receipt
  periodic_snapshot_interval:        duration | null  # e.g. "PT1H"; null = no periodic snapshots required
  snapshot_signers:                  [AttesterRole]   # who must sign snapshots; same roles as attestation_policy
```

### 5.1 Revocation-time snapshot (the primary audit point)

If `snapshot_required_at_revocation: true`:

- When a scope with budget consumption is revoked, the implementation MUST produce a `ledger_snapshot` receipt with `snapshot_type: "revocation"` before or simultaneously with the Revocation Receipt
- The Revocation Receipt SHOULD include the `receipt_hash` of this snapshot in `result.detail.ledger_snapshot_hash`
- If the implementation cannot produce the snapshot within bounded time, it must emit a Failure Receipt with a new code: `LEDGER_SNAPSHOT_FAILED`

This is the key mechanism that closes the known gap: "how much was consumed before revocation" becomes answerable from the receipt chain when this policy is enabled.

### 5.2 Absence of policy

If `ledger_policy` is absent or `snapshot_required_at_revocation: false`, snapshots are optional. Commitment Receipts still carry `budget_consumed` deltas, but cross-implementation reconstruction of totals is not guaranteed. This is the v0.2 default — implementors opt into stronger guarantees via contract policy.

---

## 6. Validation Rules

### 6.1 What validators can check from receipts alone (without snapshots)

- `budget_consumed.dimension` is a dimension declared in the contract's `budget_policy.dimensions`
- `budget_consumed.delta` is non-negative and expressed at the correct precision for the dimension
- `ledger_ref`, if present, matches the `receipt_hash` of a known Ledger Snapshot Receipt

### 6.2 What validators can check with a snapshot + subsequent receipts

- Total consumption from snapshot baseline to any point = snapshot.consumed + sum(deltas since snapshot)
- Whether total consumption exceeds the scope's ceiling at any point
- Attribution of each delta (via `initiated_by` on each Commitment Receipt)

### 6.3 What validators cannot check without full history or snapshots

- Absolute total consumption from scope issuance (if no initial snapshot exists)
- Cross-implementation consistency of `running_total` assertions

These limitations are documented, not hidden. They are the honest boundary of the hybrid model.

---

## 7. New Failure Code

This spec introduces one new failure code for the set defined in FAILURE_CODES.md:

| Code | Meaning | Required detail fields |
|---|---|---|
| `LEDGER_SNAPSHOT_FAILED` | A snapshot required by contract policy could not be produced at revocation or dissolution time | `scope_id`, `scope_hash`, `contract_id`, `snapshot_type` required, `reason` |

This code is subject to the same fail-closed semantics as `REVOCATION_STATE_UNRESOLVED`: if a required snapshot cannot be produced, the implementation must not silently proceed.

---

## 8. Relationship to Attestation

Ledger Snapshot Receipts are hashable artifacts. They can be attested using the same attestation machinery defined in `spec/attestation/ATTEST.md`:

- An Attestation Receipt may reference a Ledger Snapshot Receipt via `attests_receipt_hash`
- The `response_schema` for such an attestation would be something like `"pact.ledger_snapshot.v2"`
- The `response_hash` would cover the canonical snapshot payload

This enables a third-party auditor to attest that a specific ledger state is correct, without requiring the protocol to verify accounting independently.

This is the path toward (C)-level assurance (cross-system proof) for budget state, without requiring Pact to become a settlement layer.

---

## 9. Out of Scope (v0.2)

| Excluded | Why |
|---|---|
| Currency exchange rates | Implementation-layer semantic; Pact treats all dimensions as opaque numeric quantities |
| Multi-currency reconciliation | Requires financial settlement infrastructure outside protocol scope |
| Distributed ordering guarantees for concurrent consumers | Requires consensus mechanism; out of scope for v0.2 |
| Negative balances / credit models | Deferred; all v0.2 deltas are non-negative |
| Batch snapshot covering multiple scopes | Useful for coalition-level accounting; reserved for v0.3 |
| Ledger proof systems (ZK proofs of accounting correctness) | Future research; compatible with this design |

---

## 10. Required Changes to Other Specs

**COALITION.md v0.2:** Add `ledger_policy` as an optional field in the Coalition Contract schema. Document its semantics (§5 of this doc).

**RECEIPT.md:** Add `"ledger_snapshot"` to the list of valid `receipt_kind` values (§3). Update the kinds table. Add `LEDGER_SNAPSHOT_FAILED` to the failure codes table (§5).

**FAILURE_CODES.md:** Add `LEDGER_SNAPSHOT_FAILED` to the code table with required detail fields per §7 of this doc.

**GOTCHAS.md:** Move "Budget ledger state not captured in revocation receipts" from Open to Resolved, noting that it is resolved when `snapshot_required_at_revocation: true` is set in contract policy, and remains open for contracts without that policy.

---

## 11. Locked Invariants

| # | Invariant |
|---|---|
| 1 | The authoritative ledger is implementation-maintained; receipts declare deltas, not reconstruct totals |
| 2 | `budget_consumed.delta` is always non-negative in v0.2 |
| 3 | `budget_consumed.dimension` must match a dimension declared in the contract's `budget_policy.dimensions` |
| 4 | `running_total` is informational; validators must not treat it as authoritative |
| 5 | `ledger_ref` anchors a delta to a snapshot baseline; null is valid when no prior snapshot exists |
| 6 | `balances` in a Ledger Snapshot Receipt is sorted by `dimension` ascending before hashing |
| 7 | If `snapshot_required_at_revocation: true`, a snapshot must be produced before or simultaneously with the Revocation Receipt |
| 8 | `LEDGER_SNAPSHOT_FAILED` has fail-closed semantics; implementation must not proceed silently |
| 9 | Ledger Snapshot Receipts are hashable artifacts and may be attested via ATTEST.md machinery |
| 10 | Cross-implementation consistency of totals is not guaranteed without snapshot receipts; this is an honest boundary, not a gap |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
