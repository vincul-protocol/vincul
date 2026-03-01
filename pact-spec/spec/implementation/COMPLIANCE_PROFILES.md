# Pact Protocol — Compliance Profiles
`spec/implementation/COMPLIANCE_PROFILES.md` · Draft v0.2

---

## Purpose

Pact's core protocol specs define invariants that all conformant implementations must satisfy. Some properties, however, are not fixed by the protocol — they are *bounded* by the protocol and *declared* by implementations.

A **Compliance Profile** is a named, versioned declaration of an implementation's operational bounds. Profiles exist to:

1. Make implementation-specific limits explicit and machine-readable
2. Enable interoperability checks before a coalition is formed (can these two implementations work together?)
3. Provide the normative location for the one remaining open gap: delegation depth bounding

Profiles do not change protocol semantics. They are declarations, not extensions. An implementation that declares `max_delegation_depth: 10` is not changing the protocol; it is stating what it will enforce.

---

## 2. Profile Structure

```yaml
ComplianceProfile:
  profile_id:      string          # unique identifier for this profile; e.g. "pact-core-minimal-v0.2"
  protocol_version: string         # the Pact protocol version this profile conforms to; e.g. "0.2"
  implementation:
    name:          string          # implementation name
    version:       string          # implementation version
    vendor:        string | null

  bounds:
    max_delegation_depth:              integer | null   # maximum allowed delegation chain depth; null = unbounded (not recommended)
    max_scope_chain_length:            integer | null   # maximum number of scopes in a single DAG path; null = unbounded
    revocation_resolution_deadline_ms: integer | null   # maximum ms to confirm cascade revocation; null = unbounded (non-compliant per SEMANTICS.md §7)
    ledger_snapshot_interval_seconds:  integer | null   # if using periodic snapshots; null = no periodic snapshots
    max_receipt_chain_fanout:          integer | null   # maximum branching factor in a receipt chain; null = unbounded
    max_constraint_atoms:              integer          # maximum atoms in a ConstraintExpression; MUST be ≤ 64 (CONSTRAINT.md §3.1)
    max_constraint_nesting_depth:      integer          # maximum nesting depth; MUST be ≤ 8 (CONSTRAINT.md §3.1)

  supported_receipt_kinds:
    - string                           # list of receipt_kind values this implementation can produce and consume

  supported_failure_codes:
    - string                           # list of FailureCode values this implementation emits

  signature_algorithms:
    - string                           # e.g. ["Ed25519"]; must be a subset of protocol-defined algorithms

  attestation_schemas:
    - string | null                    # response_schema identifiers this implementation can canonicalize; null if none

  descriptor_hash:  hash               # SHA-256 of JCS(profile without descriptor_hash), domain prefix PACT_PROFILE_V1\x00
```

---

## 3. Bound Semantics

### 3.1 `max_delegation_depth`

The maximum number of hops from a root scope to any leaf scope in the delegation DAG. A scope at depth D has exactly D ancestors.

This bound closes the last open gap in GOTCHAS.md: ancestor traversal for validity checking is O(depth), and without a declared bound implementations cannot guarantee worst-case validation cost.

**Normative rule:** If `max_delegation_depth` is declared, the implementation MUST reject any delegation that would place the child scope at a depth exceeding this value. Rejection produces a Failure Receipt with `DELEGATION_MALFORMED` and `reason` stating the depth violation.

**Recommended values:**

| Profile tier | Recommended `max_delegation_depth` |
|---|---|
| Minimal | 4 |
| Standard | 10 |
| Extended | 20 |
| Unbounded (not recommended) | null |

`null` is valid but implementations declaring `null` must acknowledge unbounded O(depth) validation cost and are responsible for their own performance characteristics.

### 3.2 `revocation_resolution_deadline_ms`

The maximum time an implementation will wait to confirm cascade revocation state before failing closed (SEMANTICS.md §7). This bound must be non-null for any implementation that claims compliance with the fail-closed invariant.

**Normative rule:** If null, the implementation is non-compliant with SEMANTICS.md §7 ("implementations must ensure validation cost is bounded in practice"). Profiles with `revocation_resolution_deadline_ms: null` must be explicitly flagged as non-compliant in their `profile_id` (e.g., `"pact-experimental-unbounded-v0.2"`).

### 3.3 `max_constraint_atoms` and `max_constraint_nesting_depth`

These bounds must be ≤ the protocol maxima defined in CONSTRAINT.md §3.1 (64 atoms, depth 8). Implementations may declare tighter bounds. They may not declare looser bounds than the protocol allows.

### 3.4 `supported_receipt_kinds`

Declarations of which receipt kinds an implementation can produce and consume. A v0.2 implementation claiming full compliance must support all eight v0.2 kinds. Partial support (e.g., a read-only validator that consumes but does not produce receipts) is valid with explicit declaration.

### 3.5 All other bounds

If a bound field is `null`, the implementation declares no limit. Other implementations and coalition contracts may use this information to determine compatibility — a coalition with an implementation that declares `max_delegation_depth: 4` cannot safely include an implementation that expects to use depth-10 delegation chains.

---

## 4. Coalition Interoperability Rule

When two or more implementations participate in a coalition, the **most restrictive declared bound governs** for all shared operations.

Examples:
- Implementation A declares `max_delegation_depth: 10`; Implementation B declares `max_delegation_depth: 4` — the effective limit for this coalition is 4
- Implementation A declares `revocation_resolution_deadline_ms: 500`; Implementation B declares `2000` — the effective limit is 500 (most restrictive)
- Implementation A declares a bound; Implementation B declares null — the declared bound governs (null does not override a declaration)

**Rationale:** Coalitions must be able to operate safely across the least capable participant. A scope that is valid for implementation A but produces an O(∞) validation path for implementation B is a real interoperability failure, not a theoretical one.

Coalition Contracts SHOULD include a `required_profile_bounds` field (reserved for v0.3) that explicitly states minimum implementation requirements for participation. In v0.2, interoperability checking is implementation-defined.

---

## 5. Profile Hashing

The `descriptor_hash` for a Compliance Profile uses domain prefix `PACT_PROFILE_V1\x00`:

```
descriptor_hash = SHA-256( "PACT_PROFILE_V1\x00" || JCS(profile_without_hash) )
```

Field ordering follows JCS (RFC 8785). Arrays within the profile (e.g., `supported_receipt_kinds`, `signature_algorithms`) are sorted lexicographically before hashing — same normalization as `principals` in Coalition Contracts.

---

## 6. Standard Profile Tiers (Informative)

The following tiers are informative suggestions, not normative requirements. Implementations may use any profile name.

### 6.1 `pact-core-minimal-v0.2`

Minimum viable compliance for v0.2 implementations:

```yaml
bounds:
  max_delegation_depth: 4
  max_scope_chain_length: 8
  revocation_resolution_deadline_ms: 5000
  ledger_snapshot_interval_seconds: null
  max_receipt_chain_fanout: null
  max_constraint_atoms: 32
  max_constraint_nesting_depth: 4

supported_receipt_kinds:
  - delegation
  - commitment
  - revocation
  - revert_attempt
  - failure
  - contract_dissolution

supported_failure_codes:
  - SCOPE_EXPIRED
  - SCOPE_REVOKED
  - SCOPE_EXCEEDED
  - CEILING_VIOLATED
  - TYPE_ESCALATION
  - DELEGATION_UNAUTHORIZED
  - DELEGATION_MALFORMED
  - REVOCATION_UNAUTHORIZED
  - REVOCATION_STATE_UNRESOLVED
  - ANCESTOR_INVALID
  - CONTRACT_EXPIRED
  - CONTRACT_DISSOLVED
  - CONTRACT_NOT_ACTIVE
  - UNKNOWN

signature_algorithms:
  - Ed25519
```

### 6.2 `pact-core-standard-v0.2`

Full v0.2 compliance including attestation and budget:

All `pact-core-minimal-v0.2` bounds, plus:

```yaml
bounds:
  max_delegation_depth: 10
  max_scope_chain_length: 20
  revocation_resolution_deadline_ms: 2000
  ledger_snapshot_interval_seconds: 3600
  max_constraint_atoms: 64
  max_constraint_nesting_depth: 8

supported_receipt_kinds:
  - [all eight v0.2 kinds including attestation and ledger_snapshot]

supported_failure_codes:
  - [all v0.2 codes including BUDGET_EXCEEDED and LEDGER_SNAPSHOT_FAILED]
```

---

## 7. Closing the Last Open Gap

This document resolves the final entry in the GOTCHAS.md Known Gaps table:

> "Maximum delegation depth is not bounded in the schema — ancestor traversal cost is O(depth); implementations must self-bound via compliance profiles; no interoperable depth limit exists."

With Compliance Profiles:
- Depth limits are explicitly declared per implementation
- The coalition interoperability rule (§4) defines which limit governs
- Rejection behavior is normative (DELEGATION_MALFORMED Failure Receipt)
- The protocol geometry remains clean — no depth limit is baked into the Scope schema

---

## 8. Required Changes to Other Specs

**GOTCHAS.md:** Move "Maximum delegation depth is not bounded in the schema" from Open to Resolved, noting resolution via Compliance Profiles.

**HASHING.md §4:** Add `PACT_PROFILE_V1\x00` to the domain separation tags table.

---

## 9. Locked Invariants

| # | Invariant |
|---|---|
| 1 | Compliance Profiles are declarations, not extensions; they do not change protocol semantics |
| 2 | `max_constraint_atoms` MUST be ≤ 64; `max_constraint_nesting_depth` MUST be ≤ 8 |
| 3 | `revocation_resolution_deadline_ms: null` is non-compliant with SEMANTICS.md §7 |
| 4 | When declared, `max_delegation_depth` violations produce `DELEGATION_MALFORMED` Failure Receipts |
| 5 | The most restrictive declared bound governs across coalition participants |
| 6 | `null` does not override a declared bound in the coalition interoperability rule |
| 7 | Arrays in profile hashing are sorted lexicographically before JCS serialization |
| 8 | `PACT_PROFILE_V1\x00` is the domain prefix for profile descriptor hashes |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
