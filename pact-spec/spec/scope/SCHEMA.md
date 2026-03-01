# Pact Protocol — Scope Schema
`spec/scope/SCHEMA.md` · Draft v0.1

---

## Purpose

A **Scope** is the minimal, portable representation of **delegated, bounded authority** in Pact.

Scopes are:
- **Issued** under a Coalition Contract (or directly by a Principal)
- **Delegated** only within structural limits
- **Validated** locally (no central authority required)
- **Revoked** with cascading invalidation via the scope DAG

Scopes are not "permissions."
They are **machine-verifiable boundaries**.

---

## 1. Operation Types

### 1.1 Impact chain (partial order)

Pact defines a closed set of operation types on the impact chain:

```
OBSERVE < PROPOSE < COMMIT
```

These types represent the **kind of authority being exercised**, not the domain semantics.
Pact enforces structural safety at this level. What `calendar.events:COMMIT` does in the real world is outside Pact's reasoning boundary.

### 1.2 Type-set rule (contiguity)

A scope may hold multiple operation types, but **only as a contiguous prefix** of the impact chain:

**Allowed:**
- `{OBSERVE}`
- `{OBSERVE, PROPOSE}`
- `{OBSERVE, PROPOSE, COMMIT}`

**Disallowed:**
- `{PROPOSE}` — missing OBSERVE
- `{COMMIT}` — missing OBSERVE, PROPOSE
- `{OBSERVE, COMMIT}` — non-contiguous

This rule is enforced at issuance and re-validated at delegation. A schema that violates contiguity is malformed and must be rejected.

### 1.3 Orthogonal grants

Two orthogonal capabilities exist outside the impact chain. They are **never implied** by any type or combination of types:

| Flag | Meaning | Default |
|---|---|---|
| `delegate` | May mint a child scope (sub-delegation) | `false` |
| `revoke` | May revoke scopes within this subtree | `principal_only` |

**`COMMIT` does not imply `delegate`. Nothing implies `delegate`.**

`revoke` is always retained unconditionally by the Principal. A Coalition member may hold `revoke` only if explicitly granted via `coalition_if_granted`. This grant is not heritable by default.

---

## 2. Domain

A Scope applies within a **typed hierarchical namespace**:

```yaml
domain:
  namespace: "calendar.events"       # implementation anchor (hierarchical path)
  types: ["OBSERVE", "PROPOSE"]      # contiguous prefix of the impact chain
```

### 2.1 Namespace

A dot-separated hierarchical path that identifies the resource space this scope governs. Pact does not interpret namespace semantics. Pact does enforce that:

- Child namespace coverage ⊆ parent namespace coverage
- Namespace comparison is structural (path prefix or registered mapping)

Namespace registries are implementation-layer concerns. Pact does not require one.

### 2.2 Namespace containment rule

A namespace `A` contains namespace `B` if and only if:

```
B == A
OR
B starts with (A + ".")
```

**Examples:**
- `calendar` contains `calendar.events` ✓
- `calendar.events` contains `calendar.events.create` ✓
- `calendar.events` does **not** contain `calendar.reminders` ✗
- `calendarX` does **not** contain `calendar.events` ✗

No wildcards. No regex. No fuzzy matching.

If an implementation requires semantic containment beyond structural prefix, that must be handled by a namespace registry mapping layer. Pact core uses only this rule.

When a child scope is derived from a parent:

```
child.domain.types ⊆ parent.domain.types
```

Type escalation is a hard violation. A child scope may not hold `COMMIT` if its parent holds only `{OBSERVE, PROPOSE}`. This is checked at issuance and must be re-checkable by any validator holding both scope descriptors.

---

## 3. Predicate and Ceiling

Both `predicate` and `ceiling` are expressions in the Pact Constraint DSL (defined separately in `spec/dsl/CONSTRAINT.md`). The following invariants govern their relationship:

```
predicate ⊆ ceiling
```

- **`predicate`** — what is permitted within this scope at the time of issuance
- **`ceiling`** — the hard envelope that may never be exceeded, regardless of predicate

The ceiling is inherited downward. At delegation:

```
child.ceiling = intersect(child.ceiling, parent.ceiling)
```

A child may declare a narrower ceiling than its parent. It may never declare a wider one. If the declared child ceiling would exceed the inherited parent ceiling, the delegation is malformed and must be rejected.

---

## 4. Delegation DAG

### 4.1 Parent pointer requirement

Every delegated scope **must** carry an `issued_by_scope_id` referencing its direct parent scope. Root scopes — issued directly by a Principal or Contract runtime, not derived from another scope — set `issued_by_scope_id: null`.

This pointer is not advisory. It is a **compliance requirement**. Implementations must maintain a local scope DAG using these pointers to support:

- Ancestor validation (validity predicate, §5)
- Cascade computation (revocation, per SEMANTICS.md)
- Audit traversal

**Validation cost:** Ancestor traversal for condition 3 of the validity predicate is O(depth). Implementations MUST ensure that validation cost is bounded in practice. Implementations MAY enforce a maximum delegation depth. If depth limits are imposed, they MUST be declared in the implementation's compliance profile.

### 4.2 DAG integrity

Parent pointers must form a **directed acyclic graph**. Cycles are malformed. Implementations must reject any scope whose parent pointer chain contains a cycle or references an unresolvable scope ID.

### 4.3 Root identification

A scope is a root scope if and only if `issued_by_scope_id: null`. Root scopes must be issued by a Principal or a Contract runtime with Principal authority. Implementations must reject delegated scopes that claim root status.

---

## 5. Status and Validity

### 5.1 Status field

Every scope carries an explicit status:

| Status | Meaning |
|---|---|
| `active` | Valid for action authorization and delegation |
| `pending_revocation` | Valid for action authorization until `effective_at`; may not issue child scopes |
| `revoked` | Invalid; all descendants invalid by cascade |
| `expired` | Invalid by time; `expires_at` has passed |

Status is a derived field — its ground truth is the scope DAG plus the revocation record. Implementations must compute and expose it; they must not treat a stored status value as authoritative without re-validating against the DAG.

### 5.2 Validity predicate

A scope `S` is valid at time `t` if and only if all of the following hold:

1. `S.status ∈ {active, pending_revocation}` and, if `pending_revocation`, `t < S.effective_at`
2. `S` has not been directly revoked
3. No ancestor of `S` in the delegation DAG has been revoked
4. The governing Coalition Contract is not dissolved
5. `t < S.expires_at` (or `S.expires_at` is null)

Condition 3 requires traversal of the local scope DAG. This is why §4.1 is a compliance requirement, not a recommendation.

### 5.3 Pending revocation constraints

A scope in `pending_revocation` status:
- May authorize actions until `effective_at`
- **Must not** authorize new delegations (`delegate` effectively becomes `false`)
- Must surface its pending status to any validator that queries it

---

## 6. Full Schema (v0.1)

```yaml
Scope:
  id:                  uuid                          # globally unique scope identifier
  issued_by_scope_id:  uuid | null                   # parent scope; null for root scopes only
  issued_by:           principal_id | contract_id    # issuing authority
  issued_at:           timestamp
  expires_at:          timestamp | null

  domain:
    namespace:         hierarchical_path             # e.g. "calendar.events"
    types:             contiguous_prefix<OperationType>  # e.g. ["OBSERVE", "PROPOSE"]

  predicate:           ConstraintExpression          # what is permitted; defined in DSL spec
  ceiling:             ConstraintExpression          # hard envelope; predicate ⊆ ceiling

  delegate:            boolean                       # never implied; default false
  revoke:              "principal_only" | "coalition_if_granted"

  status:              "active" | "pending_revocation" | "revoked" | "expired"
  effective_at:        timestamp | null              # populated when pending_revocation

  descriptor_hash:     hash                          # deterministic hash of all fields above
                                                     # (excluding descriptor_hash itself)
```

### 6.1 Descriptor hash

The `descriptor_hash` is a deterministic hash over the canonical serialization of all fields except itself. It serves as:
- A tamper-evident identifier for the scope as issued
- The reference used in Delegation Receipts and Revocation Receipts
- The basis for audit comparison across implementations

Hash algorithm is specified in `spec/crypto/HASHING.md` (not yet written). All implementations must use the same canonical serialization and algorithm.

---

## 7. Delegation Constraints (summary)

When issuing a child scope from a parent, the following must all hold. Violation of any constraint renders the delegation malformed:

| Constraint | Rule |
|---|---|
| Type containment | `child.domain.types ⊆ parent.domain.types` |
| Namespace containment | `child.domain.namespace` is within `parent.domain.namespace` coverage |
| Ceiling containment | `child.ceiling ⊆ parent.ceiling` (intersection is a normalization step, not the containment rule) |
| Predicate containment | `child.predicate ⊆ child.ceiling` |
| Delegate gate | `child.delegate = true` only if `parent.delegate = true` |
| Revoke gate | `child.revoke = "coalition_if_granted"` only if explicitly authorized in parent |
| Status gate | Parent must be `active` at time of delegation; `pending_revocation` blocks delegation |

These constraints are stateless and locally verifiable given two scope descriptors. No central authority is required to validate a delegation.

---

## 8. What the Schema Does Not Cover

The following are explicitly out of scope for this document:

- **Constraint DSL syntax** — defined in `spec/dsl/CONSTRAINT.md`
- **Receipt formats** — defined in `spec/revocation/SEMANTICS.md`
- **Cryptographic encoding** — defined in `spec/crypto/` (not yet written)
- **Namespace registry** — implementation-layer concern; not part of the protocol
- **Contract dissolution** — Coalition Contract lifecycle is a separate spec

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | `predicate ⊆ ceiling` always |
| 2 | `child.ceiling ⊆ parent.ceiling` always |
| 3 | `child.domain.types ⊆ parent.domain.types` always |
| 4 | `delegate` is never implied by any operation type |
| 5 | Root scopes have `issued_by_scope_id: null`; all others must have a valid parent pointer |
| 6 | Parent pointers form a DAG; cycles are malformed |
| 7 | `pending_revocation` blocks delegation; does not yet block authorization |
| 8 | Status is computed from the DAG; stored status is not authoritative alone |
| 9 | `descriptor_hash` covers all fields and must be reproducible by any validator |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
