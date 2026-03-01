# Pact Protocol — Coalition Contract Specification
`spec/contract/COALITION.md` · Draft v0.1

---

## Purpose

A **Coalition Contract** is the formal instrument under which multiple Principals establish shared intent and bounded authority.

If a Scope defines *what* authority may be exercised, a Coalition Contract defines *who may participate*, *for what purpose*, and *under what governance rules*.

Coalition Contracts are:
- **Hashable** — every contract has a stable `descriptor_hash`
- **Immutable once activated** — no field may change after activation
- **Bounded by explicit purpose** — authority may not exceed the contract's declared scope
- **Self-describing** — validation requires only the contract object and its principal registry
- **Independent of any central authority** — validity is locally computable

They are not companies. They are not legal entities. They are cryptographically attributable coordination agreements.

---

## 1. Design Principles

1. **Explicit consent is required to activate a contract** — no implicit or implied activation
2. **Authority flows from the contract into scopes** — scopes derive from contracts, not the reverse
3. **The contract may expire or dissolve** — both are well-defined terminal states
4. **The contract never mutates** — amendments require a new contract with a new `contract_id`
5. **The contract is hash-bound** — `descriptor_hash` is the authoritative identity of a contract version

---

## 2. Coalition Contract Object

```yaml
CoalitionContract:
  contract_id:     uuid                       # globally unique contract identifier
  version:         "0.1"                      # protocol version this contract conforms to

  purpose:
    title:         string                     # short human-readable name
    description:   string                     # declarative statement of intent
    expires_at:    timestamp | null           # null = no fixed expiry

  principals:
    - principal_id:    string                 # unique identifier for this principal
      role:            string | null          # declarative label; not interpreted by protocol
      revoke_right:    boolean               # may initiate revocation of scopes under this contract

  governance:
    decision_rule:     "unanimous" | "majority" | "threshold"
    threshold:         integer | null         # required if decision_rule == "threshold"; else null
    signatory_policy:  SignatoryPolicy        # see §4

  budget_policy:
    allowed:              boolean
    dimensions:           [string] | null     # allowed budget dimensions; null if allowed == false
    per_principal_limit:  map<string, scalar> | null

  activation:
    status:        "draft" | "active" | "dissolved" | "expired"
    activated_at:  timestamp | null           # null until activation
    dissolved_at:  timestamp | null           # null unless dissolved

  descriptor_hash:  hash                     # computed per §3; excluded from its own input
```

### 2.1 Principals canonicalization

`principals` is logically an unordered set. However, because JCS preserves array insertion order, two implementations producing the same contract with principals in different order would compute different `descriptor_hash` values.

**Normative rule:** Before hashing (and before signature evaluation), implementations MUST sort `principals` by `principal_id` ascending, using Unicode code point (lexicographic) order. Any contract object whose `principals` array is not in this order is non-canonical. Implementations MUST either normalize to canonical order before hashing or reject the object as malformed.

This rule applies to any field that is logically a set but represented as a JSON array. In v0.1, `principals` is the only such field. If future versions add others (e.g., `tags`), the same rule applies.

### 2.2 Constraints

- `principals` must contain at least two entries. A single-principal contract is a scope, not a coalition.
- `threshold` must be `null` if `decision_rule != "threshold"`. It must be a positive integer ≤ `len(principals)` if `decision_rule == "threshold"`.
- `budget_policy.dimensions` must be `null` if `budget_policy.allowed == false`. It must be non-empty if `budget_policy.allowed == true`.
- `purpose.title` must be non-empty.
- `version` must match the protocol version under which the contract is validated. Validators must reject contracts with unrecognized version strings.

---

## 3. Descriptor Hash

The `descriptor_hash` is computed as defined in `spec/crypto/HASHING.md`:

```
descriptor_hash = SHA-256( "PACT_CONTRACT_V1\x00" || JCS(contract_without_hash) )
```

Fields excluded from the canonical payload:
- `descriptor_hash` itself
- Implementation-layer annotations not defined in this spec
- The `signatures` block (see §4)

The canonical serialization follows RFC 8785 (JCS) exactly. See HASHING.md §2 for field serialization rules.

A contract's `descriptor_hash` is stable across its lifetime because the contract object is immutable after activation. Unlike Scope hashes (which change on status transitions), a Contract hash is computed once and never changes. `activation.status` changes are recorded in the contract object — which means the hash computed at draft time will differ from the hash computed at active time. Receipts must always carry the `contract_hash` as it existed at the time of the authorized action.

> **Design note (implementation footgun):** Contract hashes are lifecycle-sensitive. If `activation.status`, `activation.activated_at`, or `activation.dissolved_at` are part of the hashed payload — and they are — then the `descriptor_hash` changes at each lifecycle transition. Implementations that cache `contract_hash` must invalidate that cache whenever any `activation.*` field changes. This mirrors the Scope status footgun documented in `spec/implementation/GOTCHAS.md`. Receipts must capture `contract_hash` at the moment of the authorized action, not at a later validation time.

---

## 4. Signatory Policy

The contract's `signatory_policy` defines the minimum signature requirements for each Receipt kind to be considered contract-valid. A Receipt that is structurally valid under RECEIPT.md but lacks required signatures is **contract-invalid** and must be rejected by validators.

```yaml
SignatoryPolicy:
  delegation:
    required_signers:   ["delegator"]
  commitment:
    required_signers:   ["initiator"]
  revocation:
    required_signers:   ["principal"]
  revert_attempt:
    required_signers:   ["initiator"]
  failure:
    required_signers:   []              # signatures on Failure Receipts are optional
  dissolution:
    required_signers:   ["principal"]   # all principals satisfying governance.decision_rule
```

A `contract_dissolution` Receipt is contract-valid if and only if its `signatures` block contains valid signatures from principals satisfying the contract's `governance.decision_rule` — unanimous, majority, or threshold — per §7. This is a MUST: a `contract_dissolution` Receipt lacking sufficient qualifying signatures must be rejected as contract-invalid even if it is structurally valid under RECEIPT.md.

### 4.1 Signer role definitions

| Role token | Meaning |
|---|---|
| `"delegator"` | The Principal or authorized agent issuing the child scope |
| `"initiator"` | The identity that initiated the action producing the Receipt |
| `"principal"` | The Principal whose reserved authority is being exercised; for dissolution, all principals whose signatures satisfy the governance rule |
| `"co_principal"` | Any other Principal in the coalition (used for multi-party commitment policies) |

### 4.2 Extended signatory policy

Contracts may require co-signatures for higher-impact operations. The `required_signers` array may contain multiple role tokens, all of which must be satisfied:

```yaml
commitment:
  required_signers: ["initiator", "co_principal"]   # requires both
```

If a role token is not recognized by a validator, the validator must reject the Receipt as contract-invalid.

### 4.3 Signature validation

Signatures are verified per `spec/crypto/HASHING.md §5`. For each required signer role, at least one signature must be present in the Receipt's `signatures` block whose `signer_id` resolves to a principal holding that role under this contract. Unresolvable `signer_id` values are invalid.

**A structurally valid Receipt (per RECEIPT.md) that lacks required signatures per this policy is contract-invalid and MUST be rejected by validators.** Signature policy is enforced at validation time; it is not advisory.

---

## 5. Contract Lifecycle

### 5.1 Draft

A contract begins in `draft` status.

In draft:
- No scopes may be issued under the contract
- No Receipts (other than a future `contract_formation` Receipt kind) may reference the contract
- The `descriptor_hash` is computable but not yet authoritative

Draft contracts may be modified freely. Each modification produces a new `descriptor_hash`. Draft is the only lifecycle stage in which the contract object may change.

### 5.2 Activation

A contract becomes `active` when:

1. All principals have provided activation consent (per `governance.decision_rule`)
2. Required activation signatures are recorded
3. `activation.activated_at` is set to the activation timestamp
4. `activation.status` is set to `"active"`

Upon activation, the contract object is **frozen**. No further modifications are permitted. The `descriptor_hash` computed at activation time is the authoritative hash for all subsequent Receipts.

Scopes may be issued under an active contract immediately upon activation.

### 5.3 Expiry

If `purpose.expires_at` is non-null and `now ≥ purpose.expires_at`:

- `activation.status` transitions to `"expired"`
- All scopes referencing this contract become invalid (validity predicate condition 4, SCHEMA.md §5.2)
- Any action attempted under an expired contract must produce a Failure Receipt with error code `CONTRACT_DISSOLVED`

Expiry is automatic. No Receipt is produced at the moment of expiry — the transition is a condition, not an event, consistent with the principle established in SEMANTICS.md §5 for `effective_at`. Validators apply `expires_at` deterministically.

### 5.4 Dissolution

A contract may be dissolved before expiry if the `governance.decision_rule` condition is satisfied and required dissolution signatures are provided.

Upon dissolution:
- `activation.dissolved_at` is set
- `activation.status` transitions to `"dissolved"`
- All scopes under the contract become invalid immediately
- Any subsequent action attempted under a dissolved contract must produce a Failure Receipt with error code `CONTRACT_DISSOLVED`

**v0.2 dissolution signaling:** Implementations MUST emit a `contract_dissolution` Receipt at dissolution time, per `spec/receipts/CONTRACT_DISSOLUTION.md`. The Receipt must carry both `contract_hash_before` and `contract_hash_after`, the `dissolved_at` timestamp, and signatures satisfying `signatory_policy.dissolution` and the `governance.decision_rule`. The v0.1 Failure Receipt fallback is superseded and must not be used in v0.2-conformant implementations.

**No amendment is permitted.** Dissolution is terminal. To re-establish a coalition, a new contract must be formed with a new `contract_id`.

---

## 6. Contract Validity Predicate

A Coalition Contract is valid at time `t` if and only if:

1. `activation.status == "active"`
2. `purpose.expires_at` is null, or `t < purpose.expires_at`
3. `activation.dissolved_at` is null

If any condition fails, the contract is invalid. All scopes referencing it are invalid. All Receipts attempting action under it must emit a Failure Receipt with code `CONTRACT_DISSOLVED`.

This predicate is locally computable given only the contract object. No external resolution is required.

---

## 7. Governance Semantics

### 7.1 Decision rules

| Rule | Requirement |
|---|---|
| `"unanimous"` | All principals listed in `principals` must provide a qualifying signature |
| `"majority"` | More than 50% of principals must provide a qualifying signature |
| `"threshold"` | At least `governance.threshold` principals must provide qualifying signatures |

Signature counting is deterministic:
- Each `principal_id` counts at most once, regardless of how many signatures they provide
- Duplicate signatures from the same principal are ignored (not an error)
- Signatures from identities not listed in `principals` are invalid and must be rejected

### 7.2 Revoke rights

`revoke_right: true` on a principal entry grants that principal the ability to initiate revocation of scopes under this contract, subject to the scope-level `revoke` flag (SCHEMA.md §3.1).

A principal with `revoke_right: false` may not revoke scopes under this contract, even if they hold a scope with `revoke: "coalition_if_granted"`. The contract-level right is a prerequisite; the scope-level flag is a further gate. Both must be satisfied.

Principals always retain the ability to revoke scopes they personally delegated, regardless of `revoke_right`.

---

## 8. Budget Policy

If `budget_policy.allowed == false`:
- No `BudgetAtom` expressions may appear in `predicate` or `ceiling` fields of any scope issued under this contract
- A scope containing BudgetAtoms under a budget-disallowed contract is malformed and must be rejected

If `budget_policy.allowed == true`:
- Only dimensions listed in `budget_policy.dimensions` are valid in BudgetAtoms
- BudgetAtoms referencing unlisted dimensions are malformed
- `per_principal_limit`, if non-null, defines an additional ceiling per principal across all their scopes under this contract

Budget ledger state is out of scope for v0.1. See `spec/budget/LEDGER.md` (v0.2).

---

## 9. Relationship to Other Specs

| Spec | Relationship |
|---|---|
| `spec/scope/SCHEMA.md` | Scopes carry `contract_id` and `contract_hash`; validity predicate condition 4 references contract validity |
| `spec/revocation/SEMANTICS.md` | Dissolution triggers the same cascade as scope revocation; Receipts follow SEMANTICS rules |
| `spec/dsl/CONSTRAINT.md` | Budget policy governs which BudgetAtom dimensions are valid in scope predicates |
| `spec/receipts/RECEIPT.md` | All contract-authorized events produce Receipts; signatory policy defines contract-validity of those Receipts |
| `spec/crypto/HASHING.md` | `descriptor_hash` is computed per HASHING.md using domain prefix `PACT_CONTRACT_V1\x00` |

---

## 10. Locked Invariants

| # | Invariant |
|---|---|
| 1 | Contracts are immutable after activation; amendments require a new `contract_id` |
| 2 | A coalition requires at least two principals |
| 3 | Activation requires consent per `governance.decision_rule` before any scope may be issued |
| 4 | Expiry is a condition evaluated deterministically; no Receipt is produced at the expiry moment |
| 5 | Dissolution is terminal; no amendment or reactivation is possible |
| 6 | Dissolution and expiry both produce `CONTRACT_DISSOLVED` failure codes on subsequent action attempts |
| 7 | `descriptor_hash` is computed at each lifecycle stage; Receipts capture the hash at action time |
| 8 | Signatory policy is contract-defined; a structurally valid Receipt may be contract-invalid |
| 9 | Governance signature counting is deterministic; duplicate principal signatures count once |
| 10 | `revoke_right` is a contract-level prerequisite; scope-level `revoke` flag is an additional gate |
| 11 | Budget dimensions are closed per contract; unlisted dimensions in BudgetAtoms are malformed |
| 12 | Single-principal contracts are malformed; minimum two principals required |
| 13 | `principals` MUST be sorted by `principal_id` (Unicode code point order) before hashing; unsorted contracts are non-canonical |
| 14 | Contract hashes are lifecycle-sensitive; `descriptor_hash` changes on any `activation.*` field transition; cached hashes must be invalidated accordingly |
| 15 | A structurally valid Receipt lacking required signatures per `signatory_policy` is contract-invalid and must be rejected |
| 16 | `signatory_policy.dissolution` requires signatures satisfying the `governance.decision_rule`; a `contract_dissolution` Receipt without qualifying signatures is contract-invalid |
| 17 | In v0.2, implementations MUST emit a `contract_dissolution` Receipt at dissolution time; the v0.1 Failure Receipt fallback is superseded |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
