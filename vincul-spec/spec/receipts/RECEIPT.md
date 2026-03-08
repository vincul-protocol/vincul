# Vincul Protocol — Receipt Schema
`spec/receipts/RECEIPT.md` · Draft v0.2

---

## Purpose

A **Receipt** is the canonical audit artifact of the Vincul protocol.

Receipts record protocol-relevant events that occur under the authority
of a Coalition Contract. Every delegation, commitment, revocation,
or protocol failure produces a Receipt.

Receipts are not logs. They are not notifications. They are not confirmations.

A Receipt is a **machine-verifiable, attributable, immutable claim**
that a specific event occurred under a specific authority at a specific time.

The structure of every Receipt follows a single envelope:

**Intent · Authority · Result**

- **Intent** — what was being attempted, and by whom
- **Authority** — the scope and contract under which the attempt was authorized
- **Result** — what actually happened, deterministically recorded

Every Receipt kind defined in this document must conform to this envelope.
Implementations may not define receipt kinds that omit any of the three fields.

---

## 1. Design Constraints

| Property | Requirement |
|---|---|
| **Immutable** | Once issued, a Receipt is never modified |
| **Self-contained** | A Receipt must be verifiable without resolving external state at verification time |
| **Attributable** | Every Receipt carries the identity of the issuing authority |
| **Deterministic** | Given the same inputs, the same Receipt is always produced |
| **Canonically serializable** | Two identical Receipts produce identical byte representations |
| **Hashable** | Every Receipt has a `receipt_hash` covering all fields |
| **Chainable** | Receipts may reference prior Receipts by `receipt_hash`; this forms an audit chain, not a blockchain |

Receipts are **not encrypted by default**. Confidentiality is an implementation-layer concern. 

The protocol requires that Receipts be producible and verifiable. It does not require that they be publicly visible.


---

## 2. Receipt Envelope

All Receipts share this envelope:

```yaml
Receipt:
  receipt_id:      uuid                    # globally unique receipt identifier
  receipt_kind:    ReceiptKind             # see §3
  issued_at:       timestamp               # when the receipt was produced

  intent:
    action:        string                  # human-readable verb: "delegate" | "commit" | "revoke" | "revert" | "fail"
    description:   string                  # declarative statement of what was attempted
    initiated_by:  principal_id | agent_id # who initiated the action

  authority:
    scope_id:      uuid                    # the scope under which the action was authorized
    contract_id:   uuid                    # the governing Coalition Contract
    signatories:   [principal_id]          # parties whose authority is invoked

  result:
    outcome:       "success" | "failure" | "partial" | "pending"
    detail:        ReceiptKindResult       # kind-specific result fields (see §4)

  prior_receipt:   hash | null             # receipt_hash of immediately preceding receipt in chain, if any
  receipt_hash:    hash                    # deterministic hash of all fields above (excluding receipt_hash itself)
```

All fields in the envelope are included in `receipt_hash` except `receipt_hash` itself.

### 2.1 Immutability

Once a Receipt is issued, no field may be modified. If a subsequent event modifies the situation (e.g., a revert succeeds after a Non-Revertable Notice was issued), a new Receipt is produced referencing the prior one via `prior_receipt`. The original Receipt is not amended.

### 2.2 Self-containment requirement

A Receipt must contain sufficient information to verify its claim without live resolution of external state. Specifically, verification must not require resolving live external state at verification time.

- The `scope_id` must be accompanied by the scope's `descriptor_hash` in the Authority block (so the scope as-issued can be verified without fetching it live)
- The `contract_id` must be accompanied by the contract's `descriptor_hash`
- If a Receipt references another Receipt (via `prior_receipt`), the reference is by `receipt_hash`, not by mutable identifier

In practice, implementations must use the extended authority block below, which includes the descriptor hashes required for self-contained verification.

The extended authority block:

```yaml
authority:
  scope_id:           uuid
  scope_hash:         hash
  contract_id:        uuid
  contract_hash:      hash
  signatories:        [principal_id]
```

### 2.3 Chaining

`prior_receipt` is optional. When populated, it links this Receipt to the immediately preceding Receipt in the same logical event chain (e.g., a Revert Attempt Receipt links to its triggering Revocation Receipt). Chains form a directed acyclic graph (DAG). Each receipt may reference at most one immediate predecessor, but multiple receipts may reference the same predecessor, forming a directed acyclic graph (DAG). Cycles are malformed.

The chain is an audit trail, not a consensus mechanism. No distributed agreement is required to produce or verify a chain.

---

## 3. Receipt Kinds

v0.2 defines eight Receipt kinds. No other kinds are valid in v0.2.

| Kind | When produced |
|---|---|
| `delegation` | A child scope is successfully issued from a parent |
| `commitment` | A `COMMIT`-type action is executed and produces an external side effect |
| `revocation` | A scope is revoked |
| `revert_attempt` | A revert of a prior commitment is attempted (triggered by revocation) |
| `failure` | Any protocol operation fails — authorization, validation, or revocation propagation |
| `attestation` | A fingerprinted artifact is attributed to a Commitment Receipt (`spec/attestation/ATTEST.md`) |
| `contract_dissolution` | A Coalition Contract is dissolved under governance rules (`spec/receipts/CONTRACT_DISSOLUTION.md`) |
| `ledger_snapshot` | A point-in-time snapshot of accumulated budget consumption for a scope (`spec/budget/LEDGER.md`) |

Implementations must produce the correct Receipt kind for each event. Producing no Receipt when one is required is a compliance violation. Producing the wrong kind is a compliance violation.

---

## 4. Kind-Specific Result Fields

### 4.1 Delegation Receipt

Produced when a child scope is successfully issued.

```yaml
result:
  outcome: "success"
  detail:
    child_scope_id:      uuid
    child_scope_hash:    hash        # descriptor_hash of the issued child scope
    parent_scope_id:     uuid
    types_granted:       [OperationType]
    delegate_granted:    boolean
    revoke_granted:      "principal_only" | "coalition_if_granted"
    expires_at:          timestamp | null
    ceiling_hash:        hash        # hash of the ceiling ConstraintExpression in canonical form
```

The `child_scope_hash` must match the `descriptor_hash` field on the issued Scope object. Validators must check this.

### 4.2 Commitment Receipt

Produced when a `COMMIT`-type action is executed and produces an external side effect.

```yaml
result:
  outcome: "success" | "partial" | "failure"
  detail:
    action_type:         "COMMIT"
    namespace:           hierarchical_path
    resource:            resource_identifier
    params:              map<string, scalar>      # parameters after validator evaluation and normalization
    reversible:          boolean                  # whether the commitment can be reverted
    revert_window:       duration | null          # if reversible, how long revert is available
    external_ref:        string | null            # implementation-defined external identifier (e.g. booking ID)
    budget_consumed:     map<string, scalar> | null  # budget dimensions consumed, if any
```

> **Note (non-normative):** `external_ref` is declarative. The protocol does not verify correspondence between this field and any external system. Cross-system proof of commitment is out of scope for v0.2 and may be specified in a future audit or attestation extension.

`reversible` and `revert_window` are declared by the implementation at commit time. The protocol does not compute reversibility — it records what the implementation declares. False declarations are an implementation compliance violation, not a protocol error.

### 4.3 Revocation Receipt

Produced when a scope is revoked.

```yaml
result:
  outcome: "success" | "pending"
  detail:
    revocation_root:     uuid               # the scope being directly revoked
    revoked_by:          principal_id | agent_id
    authority_type:      "principal" | "coalition_if_granted"
    effective_at:        timestamp          # when authority is withdrawn
    cascade_method:      "root+proof"       # always "root+proof" in v0.1
    revert_attempts:     [uuid]             # receipt_ids of Revert Attempt Receipts triggered
    non_revertable:      [uuid]             # receipt_ids of Non-Revertable Notice Receipts triggered
```

`outcome: "pending"` is used when `effective_at` is in the future. The Receipt is still issued immediately; it records the scheduled revocation. A second Revocation Receipt is not produced when `effective_at` arrives — the original Receipt is the authoritative record. Validators MUST apply `effective_at` deterministically; the transition at `effective_at` is treated as a condition rather than a protocol event, and therefore does not produce an additional Receipt.

### 4.4 Revert Attempt Receipt

Produced for each reversible Commitment triggered for revert by a Revocation.

```yaml
result:
  outcome: "success" | "failure" | "partial"
  detail:
    target_commitment:   uuid               # receipt_id of the Commitment Receipt being reverted
    triggered_by:        uuid               # receipt_id of the triggering Revocation Receipt
    revert_detail:       string             # implementation-defined description of what was undone
    residual:            string | null      # anything that could not be reverted, if partial
```

### 4.5 Failure Receipt

Produced when any protocol operation fails.

```yaml
result:
  outcome: "failure"
  detail:
    failed_operation:    FailureKind
    message:             string             # human-readable explanation
    error_code:          FailureCode        # machine-readable; see §5
    recoverable:         boolean
    scope_id:            uuid | null
```

Failure Receipts must still include the `intent` block, even if the operation fails before authority validation.

---

## 5. Failure Codes

*Updated in v0.2. Failure codes allow deterministic classification of protocol failures across implementations. Full normative definitions, precedence rules, and required detail fields are in `spec/receipts/FAILURE_CODES.md`. This table is the authoritative enumeration; FAILURE_CODES.md governs semantics.*

### 5.1 Scope-level codes

| Code | Meaning | v0.2 status |
|---|---|---|
| `SCOPE_EXPIRED` | Scope is invalid because `now ≥ scope.expires_at` | **Required** — emit when cause is expiry |
| `SCOPE_REVOKED` | Scope is invalid because the scope or an ancestor was explicitly revoked | **Required** — emit when cause is revocation |
| `SCOPE_EXCEEDED` | Requested action falls outside the scope's predicate | Unchanged from v0.1 |
| `CEILING_VIOLATED` | Requested action would exceed the scope's ceiling | Unchanged from v0.1 |
| `TYPE_ESCALATION` | Requested action type exceeds what the scope permits | Unchanged from v0.1 |
| `ANCESTOR_INVALID` | An ancestor scope in the DAG is revoked or invalid | Unchanged; include `ancestor_error_code` if determinable |
| `SCOPE_INVALID` | ⚠ Legacy — generic scope invalidation | Reception only; MUST NOT emit when cause is known |

### 5.2 Contract-level codes

| Code | Meaning | v0.2 status |
|---|---|---|
| `CONTRACT_EXPIRED` | Contract is invalid because `now ≥ contract.purpose.expires_at` | **Required** — emit when cause is expiry |
| `CONTRACT_DISSOLVED` | Contract is invalid because it was dissolved under governance rules | **Required** — emit when cause is dissolution |
| `CONTRACT_NOT_ACTIVE` | Contract is not active (e.g., status is `draft`) | **Required** — emit when cause is non-active status |
| `CONTRACT_INVALID` | ⚠ Legacy — generic contract invalidation | Reception only; MUST NOT emit when cause is known |

### 5.3 Delegation and revocation codes

| Code | Meaning |
|---|---|
| `DELEGATION_UNAUTHORIZED` | Delegation attempted without `delegate: true` |
| `DELEGATION_MALFORMED` | Child scope violates a containment invariant |
| `REVOCATION_UNAUTHORIZED` | Revocation attempted by a party without revoke authority |
| `REVOCATION_STATE_UNRESOLVED` | Cascade revocation state could not be confirmed; fail-closed is not optional |

### 5.4 Other codes

| Code | Meaning |
|---|---|
| `BUDGET_EXCEEDED` | A budget ceiling was reached |
| `UNKNOWN` | Failure condition not covered by defined codes |

### 5.5 Precedence (summary)

When multiple causes apply simultaneously: revocation takes precedence over expiry; dissolution takes precedence over expiry; contract-level codes take precedence over scope-level codes. See FAILURE_CODES.md §3 for full rules.

### 5.6 `message` field (v0.2 required)

v0.2 Failure Receipts MUST include a `message` field in `result.detail`: a single human-readable sentence describing what happened, written for a non-technical reviewer. No stack traces. No internal codes. See FAILURE_CODES.md §5 for examples.

---

## 6. Symmetry and Determinism Requirements

### 6.1 Symmetry

Every COMMIT action that produces a Commitment Receipt must produce a Receipt visible to all parties that possess authority over the scope under which the action was committed.

### 6.2 Determinism

Given the same inputs at the same `issued_at` timestamp, an implementation must always produce the same `receipt_hash`. Two implementations presented with identical inputs must produce identical `receipt_hash` values. This is the compliance test for canonical serialization.

### 6.3 Attribution

Every Receipt must be attributable to a specific `initiated_by` identity. Anonymous actions are not permitted. Receipts with null or unresolvable `initiated_by` are malformed.

---

## 7. What Receipts Do Not Cover

| Excluded | Where it lives |
|---|---|
| Budget ledger state at revocation | `spec/budget/LEDGER.md` v0.2 — closed when `snapshot_required_at_revocation: true` |
| Contract dissolution Receipt | `spec/receipts/CONTRACT_DISSOLUTION.md` v0.2 |
| Contract formation | `spec/contract/COALITION.md` (not yet written) |
| Identity verification of `initiated_by` | Implementation layer |
| Confidentiality / encryption of receipt content | Implementation layer |
| Receipt transport / delivery guarantees | Implementation layer |
| Cross-implementation receipt reconciliation | `spec/audit/RECONCILIATION.md` (not yet written) |

---

## 8. Locked Invariants

| # | Invariant |
|---|---|
| 1 | Every protocol event that modifies authority or produces a side effect must produce a Receipt |
| 2 | Receipts are immutable; subsequent events produce new Receipts with `prior_receipt` references |
| 3 | Every Receipt carries `scope_hash` and `contract_hash` for self-contained verification |
| 4 | `receipt_hash` covers all fields except itself and must be reproducible by any validator |
| 5 | v0.2 defines eight Receipt kinds; implementations must not invent additional kinds without a protocol revision |
| 6 | Failure Receipts are required; failing to produce one on failure is a compliance violation |
| 7 | `initiated_by` is always required; anonymous Receipts are malformed |
| 8 | Commitment Receipts must declare `reversible`; the protocol records the declaration, not the truth |
| 9 | Pending revocations produce one Receipt at scheduling time; no second Receipt at effective_at |
| 10 | Receipt chains are DAGs; cycles are malformed |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
