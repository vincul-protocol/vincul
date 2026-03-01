# Pact Protocol — Implementation Gotchas
`spec/implementation/GOTCHAS.md` · Draft v0.1 (updated for v0.2)

---

## Purpose

This document collects known implementation pitfalls in Pact v0.1 — places where the protocol spec is correct and internally consistent, but where the correct behavior is non-obvious and easy to get wrong.

Each entry names the trap, explains why it exists, states the correct behavior, and references the authoritative spec section.

This document is non-normative. It does not add requirements beyond what the referenced specs state. It exists to prevent subtle bugs in compliant implementations.

---

## Gotcha 1 — Scope hashes are lifecycle-sensitive

**The trap:** Caching a scope's `descriptor_hash` and reusing it across status transitions.

**Why it happens:** `descriptor_hash` is computed over all Scope fields including `status` and `effective_at` (SCHEMA.md §6.1). When a scope transitions from `active` to `pending_revocation`, or from `pending_revocation` to `revoked`, these fields change — and so does the hash.

**The consequence:** A Receipt that carries a stale `scope_hash` (e.g., the hash computed when the scope was `active`, used in a Receipt produced after the scope became `pending_revocation`) is carrying an incorrect authority reference. Validators that recompute the hash from the current scope state will see a mismatch and must treat the Receipt as unverifiable.

**Correct behavior:** Never cache `descriptor_hash` across a status or `effective_at` change. Recompute the hash at Receipt production time from the scope's current field values. The hash in a Receipt's `authority.scope_hash` must reflect the scope's state *at the moment the action was authorized*, not at a later validation time.

**Reference:** `spec/scope/SCHEMA.md §6.1` (design note), `spec/crypto/HASHING.md §6.1`

---

## Gotcha 2 — Contract hashes are lifecycle-sensitive

**The trap:** Caching a contract's `descriptor_hash` and reusing it after any `activation.*` field changes.

**Why it happens:** `descriptor_hash` is computed over all Coalition Contract fields including `activation.status`, `activation.activated_at`, and `activation.dissolved_at` (COALITION.md §3). A contract that transitions from `draft` to `active` to `dissolved` produces a different hash at each stage because those fields change.

**The consequence:** Identical to Gotcha 1 for scopes. A Receipt carrying a stale `contract_hash` will fail recomputation by validators.

**Correct behavior:** Invalidate any cached `contract_hash` whenever `activation.status`, `activation.activated_at`, or `activation.dissolved_at` changes. Receipts must capture `contract_hash` at the moment of the authorized action.

**Reference:** `spec/contract/COALITION.md §3` (design note), `spec/crypto/HASHING.md §6.3`

---

## Gotcha 3 — Pending revocation blocks delegation, not authorization

**The trap:** Treating `pending_revocation` as equivalent to `revoked` for all purposes.

**Why it happens:** `pending_revocation` is an intermediate state: the scope is valid for action authorization until `effective_at`, but may not issue child scopes.

**The consequence:** An implementation that denies all actions from a `pending_revocation` scope is being more restrictive than the protocol requires — which may appear safe but breaks valid use cases within the pending window. Conversely, an implementation that allows new delegation from a `pending_revocation` scope is non-compliant.

**Correct behavior:**
- `pending_revocation` scope: **permit** action authorization (if `now < effective_at`)
- `pending_revocation` scope: **deny** any new delegation (immediately, regardless of `effective_at`)
- At `effective_at`: treat as `revoked` for all purposes

**Reference:** `spec/scope/SCHEMA.md §5.3`, `spec/revocation/SEMANTICS.md §5.2`

---

## Gotcha 4 — Principals array ordering affects contract hash

**The trap:** Producing a Coalition Contract with `principals` in whatever order the application assembled them, then computing `descriptor_hash` without sorting first.

**Why it happens:** JCS (RFC 8785) sorts object *keys* lexicographically, but preserves array *element* order. Two implementations that produce the same contract with `principals` in different order will compute different hashes, making their contracts mutually unverifiable.

**The consequence:** Cross-implementation receipt validation fails silently — the `contract_hash` in a Receipt produced by implementation A will not match what implementation B computes from the same contract object.

**Correct behavior:** Before computing `descriptor_hash`, sort `principals` by `principal_id` ascending using Unicode code point (lexicographic) order. This normalization must be applied consistently by all implementations. The same rule applies to any future array fields that are logically sets.

**Reference:** `spec/contract/COALITION.md §2.1`, `spec/crypto/HASHING.md §2`

---

## Gotcha 5 — Status is derived, not authoritative when stored

**The trap:** Trusting the `status` field on a stored Scope object without revalidating against the scope DAG.

**Why it happens:** `status` is convenient to store, but its ground truth is the scope DAG plus revocation records. A stored `status: active` on a scope whose ancestor was revoked is stale — the scope is actually invalid.

**The consequence:** An implementation that skips DAG traversal and trusts stored status may authorize actions under revoked scopes. This is a structural safety violation — exactly the failure mode Pact's bounded authority model exists to prevent.

**Correct behavior:** Treat stored `status` as a cache hint only. Always revalidate against the full validity predicate (SCHEMA.md §5.2) before authorizing any action. The four conditions must all be satisfied; stored status satisfies only condition 1 at best.

**Reference:** `spec/scope/SCHEMA.md §5.1`, `spec/scope/SCHEMA.md §5.2`

---

## Gotcha 6 — ~~Expiry and revocation are distinct failure modes~~ (Resolved in v0.2)

**Resolved by:** `spec/receipts/FAILURE_CODES.md` v0.2

v0.1 implementations emitting `SCOPE_INVALID` or `CONTRACT_DISSOLVED` for both expiry and revocation cases should migrate to the specific v0.2 codes:

- Expired scope → `SCOPE_EXPIRED`
- Revoked scope → `SCOPE_REVOKED`
- Expired contract → `CONTRACT_EXPIRED`
- Dissolved contract → `CONTRACT_DISSOLVED`

When both causes apply, revocation/dissolution takes precedence (see FAILURE_CODES.md §3). The `message` field is now required and must be human-readable. See FAILURE_CODES.md for full migration details.

---

## Gotcha 7 — Failure-closed under revocation uncertainty is not optional

**The trap:** Falling back to "last known valid" state when revocation cascade cannot be confirmed.

**Why it happens:** Failing closed is disruptive. It's tempting to allow actions to continue while revocation propagates, especially in distributed implementations where DAG state may be momentarily inconsistent.

**The consequence:** This is the exact failure mode that makes revocation toothless. If authority can persist because confirmation is slow, the ceiling guarantee is broken. An implementation that fails open under uncertainty is non-compliant, regardless of how rare the condition is in practice.

**Correct behavior:** If cascade revocation state cannot be confirmed within the implementation's bounded time:
1. Deny all action authorizations in the affected scope subtree
2. Emit a Failure Receipt with `error_code: REVOCATION_STATE_UNRESOLVED`
3. Do not fall back to last-known-valid

**Reference:** `spec/revocation/SEMANTICS.md §7`

---

## Gotcha 8 — `reversible: true` on a Commitment Receipt is a declaration, not a guarantee

**The trap:** Assuming that a Commitment Receipt with `reversible: true` means the implementation will always succeed in reverting the action when triggered by revocation.

**Why it happens:** The protocol records the implementation's declaration at commit time. It cannot verify it.

**The consequence:** If a revert attempt fails on an action that was declared reversible, the protocol produces a Revert Attempt Receipt with `outcome: failure`. This is correct behavior — but if an implementation declared `reversible: true` carelessly (e.g., always), the audit trail fills with failed revert attempts that could have been avoided with an honest `reversible: false` declaration.

**Correct behavior:** Declare `reversible: true` only if the implementation has a concrete mechanism to undo the action. When uncertain, declare `reversible: false` and emit a Non-Revertable Notice Receipt at revocation time. Honest declarations make revocation audits meaningful.

**Reference:** `spec/receipts/RECEIPT.md §4.2`, `spec/revocation/SEMANTICS.md §4.3`

---

## Known Gaps (v0.1 → v0.2)

These are protocol-level gaps, not implementation errors. Open gaps are ordered by likelihood × damage in first implementation.

### Open gaps

There are no open protocol-level gaps in v0.2. All known gaps have been resolved or explicitly bounded.

### Resolved gaps

| Gap | Resolved in | Notes |
|---|---|---|
| `external_ref` on Commitment Receipts is unverifiable | v0.2 — `spec/attestation/ATTEST.md` | Attestation Receipt provides attributable fingerprint path. Implementations should update Commitment Receipt consumers to check for corresponding Attestation Receipts. |
| No distinct error code for scope expiry vs revocation | v0.2 — `spec/receipts/FAILURE_CODES.md` | `SCOPE_EXPIRED` and `SCOPE_REVOKED` are now distinct required codes. `CONTRACT_EXPIRED` and `CONTRACT_DISSOLVED` likewise. v0.1 generic codes remain valid for reception but must not be emitted when cause is known. |
| `contract_dissolution` Receipt kind not yet defined | v0.2 — `spec/receipts/CONTRACT_DISSOLUTION.md` | First-class event Receipt defined. The v0.1 Failure Receipt fallback is superseded. COALITION.md `signatory_policy` gains a `dissolution` entry. |
| Budget ledger state not captured in revocation receipts | v0.2 — `spec/budget/LEDGER.md` | Closed when `snapshot_required_at_revocation: true` is set in contract policy. For contracts without that policy, the gap remains open by design — an honest boundary, not a defect. |
| Maximum delegation depth is not bounded in the schema | v0.2 — `spec/implementation/COMPLIANCE_PROFILES.md` | Implementations declare bounds via Compliance Profiles. The most restrictive declared bound governs in a coalition. Depth violations produce `DELEGATION_MALFORMED` Failure Receipts. The protocol schema remains clean. |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
