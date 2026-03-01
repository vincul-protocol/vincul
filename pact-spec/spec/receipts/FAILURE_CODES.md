# Pact Protocol — Failure Codes
`spec/receipts/FAILURE_CODES.md` · Draft v0.2

---

## Purpose

Pact Failure Receipts exist to make protocol failure modes **legible and distinguishable** in audit logs, dashboards, and compliance reviews.

In v0.1, implementations emitted generic invalidation codes (`SCOPE_INVALID`, `CONTRACT_DISSOLVED`) for multiple distinct causes. This immediately produces confusion during debugging and auditing: "Did this scope die naturally or was it killed?" is unanswerable from generic codes alone.

This document introduces distinct failure codes for:
- **scope expiry** vs **scope revocation**
- **contract expiry** vs **contract dissolution**

It also defines required detail fields per code and precedence rules when multiple causes apply.

This is a v0.2 change. It is backward-compatible: v0.1 generic codes remain valid for receipt reception, but v0.2 emitters must prefer the specific codes.

---

## 1. Normative Definitions

### 1.1 Failure Receipt

A Failure Receipt is a Receipt with:
- `receipt_kind: "failure"`
- `result.outcome: "failure"`
- `result.detail.error_code: <FailureCode>`

Failure Receipts use the standard Receipt envelope defined in `spec/receipts/RECEIPT.md`.

### 1.2 Terminology

- **Expired** — invalid due to a time bound (`expires_at`) set at issuance; no actor triggered this
- **Revoked** — invalid due to an explicit revocation action by an authorized identity
- **Dissolved** — invalid due to explicit contract dissolution under governance rules

These are distinct semantic states. They must not be conflated in emitted codes, audit logs, or user-facing messages.

---

## 2. FailureCode Enum (v0.2)

Implementations MUST use the following `error_code` values exactly as specified. Values are case-sensitive strings.

### 2.1 Scope-level codes

| Code | Meaning | Required detail fields |
|---|---|---|
| `SCOPE_EXPIRED` | Scope is invalid because `now ≥ scope.expires_at` | `scope_id`, `scope_hash`, `expires_at` |
| `SCOPE_REVOKED` | Scope is invalid because the scope or an ancestor was explicitly revoked | `scope_id`, `scope_hash`, `revocation_root_scope_id`, `effective_at`, `revocation_receipt_hash` (if known) |
| `SCOPE_INVALID` | ⚠ Legacy — generic invalidation; backward compatibility only | `scope_id`, `scope_hash`, `reason` |

**v0.2 rule:** Emitters MUST emit `SCOPE_EXPIRED` or `SCOPE_REVOKED` when applicable. Emitters MUST NOT emit `SCOPE_INVALID` for expiry or revocation cases.

`SCOPE_NOT_YET_VALID` is reserved for implementations that support delayed scope activation. It is not required in v0.2 and carries no normative semantics until a delayed-activation spec is written.

### 2.2 Contract-level codes

| Code | Meaning | Required detail fields |
|---|---|---|
| `CONTRACT_EXPIRED` | Contract is invalid because `now ≥ contract.purpose.expires_at` | `contract_id`, `contract_hash`, `expires_at` |
| `CONTRACT_DISSOLVED` | Contract is invalid because it was dissolved under governance rules | `contract_id`, `contract_hash`, `dissolved_at`, `dissolution_receipt_hash` (if known) |
| `CONTRACT_NOT_ACTIVE` | Contract is invalid because its status is not `active` (e.g., `draft`) | `contract_id`, `contract_hash` (if known), `activation_status` |
| `CONTRACT_INVALID` | ⚠ Legacy — generic invalidation; backward compatibility only | `contract_id`, `contract_hash` (if known), `reason` |

**v0.2 rule:** Emitters MUST emit `CONTRACT_EXPIRED`, `CONTRACT_DISSOLVED`, or `CONTRACT_NOT_ACTIVE` when applicable. Emitters MUST NOT emit `CONTRACT_INVALID` for those cases.

### 2.3 Retained codes from v0.1

The following codes carry over from v0.1 without change:

| Code | Meaning |
|---|---|
| `SCOPE_EXCEEDED` | Requested action falls outside the scope's predicate |
| `CEILING_VIOLATED` | Requested action would exceed the scope's ceiling |
| `TYPE_ESCALATION` | Requested action type exceeds what the scope permits |
| `DELEGATION_UNAUTHORIZED` | Delegation attempted without `delegate: true` |
| `DELEGATION_MALFORMED` | Child scope violates a containment invariant |
| `REVOCATION_UNAUTHORIZED` | Revocation attempted without revoke authority |
| `REVOCATION_STATE_UNRESOLVED` | Cascade state cannot be confirmed; must fail-closed |
| `BUDGET_EXCEEDED` | A budget ceiling was reached |
| `ANCESTOR_INVALID` | An ancestor scope in the DAG is revoked or invalid |
| `UNKNOWN` | Failure condition not covered by defined codes |

`ANCESTOR_INVALID` in v0.2 should be accompanied by the most specific available ancestor code (i.e., whether the ancestor was expired or revoked) in `result.detail.ancestor_error_code` if determinable.

---

## 3. Precedence Rules

When multiple invalidation causes apply simultaneously, emitters MUST choose the most specific and most intentional code.

### 3.1 Scope: revocation over expiry

If a scope is both expired and revoked:

```
emit SCOPE_REVOKED
```

Revocation is an explicit withdrawal of authority and must remain visible in audit records even when expiry also holds. An auditor reviewing a revoked scope must see that an actor chose to withdraw authority — not that the scope aged out.

### 3.2 Contract: dissolution over expiry

If a contract is both expired and dissolved:

```
emit CONTRACT_DISSOLVED
```

Dissolution is an explicit governance action. The same reasoning applies: the audit record must reflect that a decision was made, not that a clock ran out.

### 3.3 Contract invalidity over scope invalidity

If an action fails due to both scope invalidation and contract invalidity:

```
emit the CONTRACT_* code as primary error_code
include scope-level status in result.detail.scope_error_code
```

The contract is the outer validity boundary. Its failure is the more fundamental cause.

---

## 4. Required Failure Receipt Detail Fields (v0.2)

Every v0.2 Failure Receipt MUST include the following fields in `result.detail`:

```yaml
result:
  outcome: "failure"
  detail:
    error_code:        <FailureCode>          # required; one of the defined codes
    message:           string                 # required; see §5
    recoverable:       boolean                # required; same semantics as v0.1
    scope_id:          uuid | null
    scope_hash:        hash | null
    contract_id:       uuid | null
    contract_hash:     hash | null

    # Code-specific required fields (per §2):
    # SCOPE_EXPIRED:       expires_at
    # SCOPE_REVOKED:       revocation_root_scope_id, effective_at, revocation_receipt_hash
    # CONTRACT_EXPIRED:    expires_at
    # CONTRACT_DISSOLVED:  dissolved_at, dissolution_receipt_hash
    # CONTRACT_NOT_ACTIVE: activation_status
    # ANCESTOR_INVALID:    ancestor_scope_id, ancestor_error_code (if determinable)

    # Optional supplementary fields:
    scope_error_code:  <FailureCode> | null   # set when CONTRACT_* is primary and scope also invalid
    ancestor_error_code: <FailureCode> | null # set when ANCESTOR_INVALID is emitted
```

Fields that are unknown at failure time (e.g., `scope_hash` if the scope cannot be resolved) MUST be set to `null`, not omitted.

---

## 5. Message Field Requirements

The `message` field in `result.detail` is required in v0.2. It must be:

- **Human-readable** — written for a non-technical user or compliance reviewer, not an engineer
- **One sentence** — concise; no stack traces, no internal error codes, no implementation-specific jargon
- **Factual** — state what happened, not what to do about it

Good examples:
```
"This scope expired on 2025-03-01 and is no longer valid."
"Authority for this scope was withdrawn by principal:alice at 14:32 UTC."
"This contract was dissolved by unanimous coalition decision on 2025-02-15."
"This contract is still in draft status and has not been activated."
```

Bad examples:
```
"SCOPE_INVALID: err=expiry ts=1741344000"   # internal format
"Scope validation failed."                   # uninformative
"Contact your administrator."                # deflection, not a fact
```

The `message` field is non-normative for protocol purposes — validators do not parse it. It is normatively required to exist and to follow these guidelines.

---

## 6. Backward Compatibility

### 6.1 Receiving v0.1 codes

Validators SHOULD continue to accept v0.1 generic codes (`SCOPE_INVALID`, `CONTRACT_INVALID`, `CONTRACT_DISSOLVED` used generically). When received, validators SHOULD surface a warning in audit tooling:

> "v0.1 generic invalidation code received; specific cause (expiry vs revocation) is indeterminate."

Validators MUST NOT reject v0.1 Receipts solely because they use generic codes.

### 6.2 Emitting v0.2 codes

Emitters conforming to v0.2 MUST prefer the specific v0.2 codes in all cases where the cause is determinable. Generic codes (`SCOPE_INVALID`, `CONTRACT_INVALID`) are permitted only for:

- Legacy interoperability with v0.1 consumers that cannot handle new codes
- Unknown or unclassifiable failure reasons (rare; should be logged and investigated)

Emitting a generic code when the specific cause is known is a v0.2 compliance violation.

---

## 7. Required Changes to Other Specs

### 7.1 RECEIPT.md §5

Replace the failure code table with the v0.2 codes from §2 of this document. Mark `SCOPE_INVALID` and `CONTRACT_INVALID` as legacy. Add `SCOPE_EXPIRED`, `SCOPE_REVOKED`, `CONTRACT_EXPIRED`, `CONTRACT_DISSOLVED`, `CONTRACT_NOT_ACTIVE`.

### 7.2 GOTCHAS.md

Update Gotcha 6 ("expiry vs revocation conflation") to mark it as resolved by this document. Update the Known Gaps table to move "expiry vs revocation codes" to the Resolved section alongside the `external_ref` gap closed by ATTEST.md.

---

## 8. Non-Goals

This document does not specify:

- Proof of external system state (see `spec/attestation/ATTEST.md`)
- Budget ledger snapshots (see `spec/budget/LEDGER.md`, v0.2)
- Contract dissolution event receipts (separate spec, v0.2)
- Delegation depth limits (implementation compliance profiles)
- Attestation-specific failure codes (deferred)

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | `SCOPE_EXPIRED` and `SCOPE_REVOKED` are distinct codes; emitters must not conflate them |
| 2 | `CONTRACT_EXPIRED` and `CONTRACT_DISSOLVED` are distinct codes; emitters must not conflate them |
| 3 | When both expiry and revocation apply to a scope, `SCOPE_REVOKED` takes precedence |
| 4 | When both expiry and dissolution apply to a contract, `CONTRACT_DISSOLVED` takes precedence |
| 5 | Contract-level failure codes take precedence over scope-level codes when both apply |
| 6 | `message` is required in v0.2; it must be human-readable and one sentence |
| 7 | v0.1 generic codes remain valid for receipt reception; emitters must prefer v0.2 specific codes |
| 8 | `null` fields are included explicitly; unknown fields are never omitted |
| 9 | `REVOCATION_STATE_UNRESOLVED` semantics are unchanged from v0.1; fail-closed is not optional |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
