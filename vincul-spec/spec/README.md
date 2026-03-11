# Vincul Protocol — Specification Index
`spec/` · v0.2

This directory contains the complete Vincul Protocol specification.
All documents are normative unless marked otherwise.

---

## Reading order (recommended)

Start with PHILOSOPHY.md and GLOSSARY.md at the repo root, then:

1. `spec/scope/SCHEMA.md` — scope structure, delegation invariants, validity predicate
2. `spec/revocation/SEMANTICS.md` — revocation cascade, fail-closed semantics
3. `spec/dsl/CONSTRAINT.md` — constraint expression language
4. `spec/contract/COALITION.md` — coalition contract schema and governance
5. `spec/receipts/RECEIPT.md` — receipt envelope, all eight kinds
6. `spec/receipts/FAILURE_CODES.md` — failure code enum and precedence rules
7. `spec/receipts/CONTRACT_DISSOLUTION.md` — dissolution event receipt
8. `spec/crypto/HASHING.md` — JCS canonicalization, domain tags, test vectors
9. `spec/attestation/ATTEST.md` — attestation receipt (v0.2)
10. `spec/budget/LEDGER.md` — budget ledger, snapshots (v0.2)
11. `spec/implementation/COMPLIANCE_PROFILES.md` — declared bounds, interoperability
12. `spec/implementation/GOTCHAS.md` — known footguns, resolved gaps
13. `spec/sdk/SDK_BOUNDARY.md` — SDK center of gravity, normative vs reference, golden flows

---

## Document map

```
spec/
  scope/
    SCHEMA.md                   Scope descriptor schema and validity predicate
  revocation/
    SEMANTICS.md                Revocation semantics, cascade, fail-closed
  dsl/
    CONSTRAINT.md               Constraint DSL — grammar, normal form, evaluation
  contract/
    COALITION.md                Coalition Contract schema, governance, dissolution
  receipts/
    RECEIPT.md                  Receipt envelope; all eight v0.2 kinds
    FAILURE_CODES.md            Failure code enum, precedence, message requirements
    CONTRACT_DISSOLUTION.md     contract_dissolution receipt kind
  crypto/
    HASHING.md                  JCS, domain separation, test vectors (13 vectors)
  attestation/
    ATTEST.md                   Attestation receipt kind; signature model
  budget/
    LEDGER.md                   Budget ledger model; ledger_snapshot receipt kind
  implementation/
    COMPLIANCE_PROFILES.md      Implementation-declared bounds; interoperability rule
    GOTCHAS.md                  Implementation footguns; resolved gap history
  transport/
    VINCULNET.md                VinculNet Stage 1: envelope, handshake, peer registry
  sdk/
    SDK_BOUNDARY.md             SDK boundary: normative interop, pluggable transport, golden flows
```

---

## Protocol version

**v0.2** — complete geometry, no open gaps.

v0.1 specs (SCHEMA, SEMANTICS, CONSTRAINT, COALITION, RECEIPT, HASHING) remain
valid. v0.2 adds ATTEST, LEDGER, FAILURE_CODES, CONTRACT_DISSOLUTION,
COMPLIANCE_PROFILES and updates RECEIPT and COALITION in place.

---

## Compliance verification

Run the test vector generator to verify your hashing implementation:

```bash
python3 tools/test_vectors/generate.py
```

All 13 expected hashes are in `spec/crypto/HASHING.md §7`.
A conformant implementation must produce identical hashes before any
business logic is considered correct.

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
