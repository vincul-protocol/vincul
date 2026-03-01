# spec/revocation/SEMANTICS.md
**Pact Protocol — Revocation Semantics v0.1**

---

## 1. Purpose

This document defines the authoritative semantics for scope revocation in Pact. Revocation is a first-class protocol operation, not an implementation concern. Its correctness properties must hold across all compliant implementations.

---

## 2. Core Invariant

**Revocation removes authority structurally, not normatively.**

When a scope is revoked, no action permitted by that scope — or any scope derived from it — may be authorized afterward. This guarantee must not depend on implementation goodwill, network consistency, or downstream acknowledgment.

---

## 3. Authority to Revoke

### 3.1 Principal Revocation
The Principal retains unconditional revocation authority over every scope issued under their contract. This right is non-delegable and non-waivable. No contract term may remove it.

### 3.2 Coalition Revocation
A Coalition member may revoke a scope only if:
- The governing Coalition Contract explicitly grants `revoke: coalition_if_granted`, **and**
- The scope being revoked was issued within that Coalition's authority boundary, **and**
- The revocation does not exceed the revoking member's own scope ceiling.

Coalition revocation is always explicitly granted. It is never implied by any other capability, including `DELEGATE`.

### 3.3 No Delegated Revocation
An agent holding a delegated scope may not revoke its own parent scope, sibling scopes, or any scope outside its own issued subtree. Revocation does not flow downward from delegates.

---

## 4. Cascade Rules

### 4.1 Default: Cascading Invalidation
Revoking a scope invalidates all descendant scopes that trace their `issued_by_scope_id` to the revoked scope, transitively.

This is the protocol default. It is not configurable by implementations.

**Rationale:** Authority zombies — child scopes continuing to operate after upstream consent is withdrawn — are a structural failure mode. Cascading invalidation is the only rule consistent with bounded authority.

### 4.2 Scope Validity Predicate
A scope `S` is valid at time `t` if and only if:

```
1. t < S.expires_at  (or S.expires_at is null)
2. S has not been directly revoked
3. No ancestor of S in the delegation chain has been revoked
4. The governing Coalition Contract is not dissolved
```

All four conditions are necessary. None is sufficient alone. Validation is decidable given a local scope DAG.

### 4.3 In-Flight Actions
Revocation stops future authority. It does not undo past committed actions.

If an action was committed before revocation took effect, the action stands. Revocation produces:

- A **Revocation Receipt** (see §6.2) naming the revocation root and effective timestamp
- For each committed action that is **marked reversible** in its Commitment Receipt: an automatic revert attempt, recorded as a separate **Revert Attempt Receipt**
- For each committed action that is **not reversible**: a **Non-Revertable Notice Receipt**

The protocol does not perform magical undo. It produces auditable records of what can and cannot be unwound.

---

## 5. Timing

### 5.1 Effective Timestamp
Every revocation carries an `effective_at` timestamp. Authority is withdrawn at that instant.

Default: `effective_at = now` (immediate).

A contract may define a **propagation delay** — a bounded window during which revocation is queued but not yet effective. This window must be:
- Defined in the Coalition Contract before any scope is issued under it
- Bounded (no open-ended delays)
- Honored as a ceiling, not a floor (implementations may propagate faster, never slower)

### 5.2 Scheduling Constraint
A revocation with a future `effective_at` must be treated as **pending**. During the pending window:
- The scope remains valid for action authorization
- The pending revocation must be visible to any validator with access to the scope DAG
- No new delegation from the pending-revoked scope may be issued

---

## 6. Required Receipts

### 6.1 Delegation Receipt
Produced when a scope is granted.

```
{
  intent:    "delegate",
  parent_scope_id:  <scope_id>,
  child_scope:      <full scope descriptor>,
  authority:        <parent scope + contract reference + signatories>,
  issued_at:        <timestamp>,
  receipt_hash:     <deterministic hash of above>
}
```

The `child_scope` field includes the full `{domain, predicate, ceiling, types, delegate, revoke}` descriptor so that the delegation is self-contained and auditable without live resolution.

### 6.2 Revocation Receipt
Produced when a scope is revoked.

```
{
  intent:           "revoke",
  revocation_root:  <scope_id>,
  authority:        <revoking principal or coalition grant reference>,
  effective_at:     <timestamp>,
  cascade_method:   "root+proof",
  result: {
    revoked_root:      <scope_id>,
    descendant_proof:  "computed from local scope DAG via parent pointers",
    revert_attempts:   [<revert_attempt_receipt_id>, ...],
    non_revertable:    [<non_revertable_notice_receipt_id>, ...]
  },
  receipt_hash:     <deterministic hash of above>
}
```

**Cascade method — Root + Proof:** The revocation receipt names only the revocation root. Each implementation computes the revoked descendant set from its local scope DAG using parent pointers. Any validator can verify membership. This avoids unbounded receipt size while preserving auditability.

### 6.3 Revert Attempt Receipt
Produced for each reversible committed action triggered by revocation.

```
{
  intent:         "revert",
  triggered_by:   <revocation_receipt_id>,
  target_action:  <commitment_receipt_id>,
  result:         "success" | "failed" | "partial",
  detail:         <implementation-defined>,
  receipt_hash:   <deterministic hash of above>
}
```

### 6.4 Non-Revertable Notice Receipt
Produced for each committed action that cannot be reversed.

```
{
  intent:         "non_revertable_notice",
  triggered_by:   <revocation_receipt_id>,
  target_action:  <commitment_receipt_id>,
  reason:         <why revert is not possible>,
  receipt_hash:   <deterministic hash of above>
}
```

---

## 7. Failure-Closed Behavior

If an implementation cannot confirm the revoked descendant set within a bounded time:

1. It **must deny** all action authorizations within the affected scope subtree
2. It **must produce** a **Failure Receipt** with `reason: "revocation_state_unresolved"`
3. It **must not** fall back to last-known-valid state

**The protocol fails closed. Uncertainty is not permission.**

This is not optional. Implementations that fail open under revocation uncertainty are non-compliant.

---

## 8. What Revocation Does Not Cover

Revocation semantics are scoped to authority removal. This document does not govern:

- **Consent withdrawal** at the contract level (that is Coalition Contract dissolution, a separate operation)
- **Expiry** (handled by `expires_at` on the scope; not a revocation event)
- **Predicate narrowing** (modifying what a scope permits without removing it; defined in the Delegation Amendment spec, not yet written)

---

## 9. Locked Invariants

The following are protocol invariants. They may not be overridden by contract terms, implementation configuration, or Coalition agreement.

| # | Invariant |
|---|-----------|
| 1 | Revoking a parent invalidates all descendants (cascading, by default) |
| 2 | In-flight committed actions are not undone; receipts are produced |
| 3 | Revocation uncertainty requires fail-closed behavior |
| 4 | Principal revocation authority is unconditional and non-delegable |
| 5 | `DELEGATE` does not imply revocation authority |
| 6 | No new delegation may be issued from a pending-revoked scope |
| 7 | `effective_at` is a ceiling on delay, not a floor |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
