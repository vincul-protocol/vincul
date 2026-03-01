# Pact Protocol — Philosophy
`spec/PHILOSOPHY.md` · Draft v0.1

---

## Preamble

Every day, humans attempt to coordinate with each other.

Most coordination fails silently — not because people are untrustworthy,
but because shared intent has no standard form.
Authority is assumed, not declared.
Outcomes are disputed, not recorded.

Pact is the attempt to give shared intent a standard form.

---

## 1. What Is a Boundary?

A boundary is an explicit limit on authority.

A boundary defines:
- Who may act
- On what
- For what purpose
- Under which conditions
- For how long

Boundaries reduce ambiguity.
Ambiguity is the root cause of coordination failure.

In Pact, every collective action must be bounded.
If authority is not bounded, it is not valid under the protocol.

Boundaries must be:
- Explicit
- Machine-verifiable
- Human-readable
- Time-scoped by default

---

## 2. What Is a Receipt?

A receipt is the canonical record of a collective action.

Every action under Pact must generate a receipt structured as:

**Intent · Authority · Result**

### Intent
What the group agreed to attempt.

### Authority
The specific boundary that permitted the action:
- Coalition Contract ID
- Signatories
- Vote threshold (if applicable)
- Capability scope
- Timestamp

### Result
What actually occurred.

A receipt must be:
- Deterministic
- Verifiable by all parties
- Portable across implementations
- Immutable once issued

In multi-party actions, receipts must be **symmetric**.
Every party sees the same narrative.
Asymmetric information about a shared action is a protocol violation.

Shared transparency is not a feature.
It is a structural requirement for legitimate collective action.
When everyone sees the same record, blame dissolves into authorship.

If an action cannot produce a receipt in this format,
it does not conform to Pact.

---

## 3. The Atomic Unit of Collective Action

Pact asserts that the atomic unit of collective action is:

**Intent + Authority + Result**

This is not an invention.
It is a formalization of how humans already coordinate.

When collective action fails, it fails because:
- Intent was unclear
- Authority was ambiguous
- Result was disputed

Pact does not eliminate human conflict.
It eliminates structural ambiguity.

---

## 4. Consent Is the Root of Authority

All authority in Pact derives from explicit, revocable consent.

Consent must be:
- Affirmative
- Contextual
- Specific to a boundary
- Revocable within defined constraints

Implicit agreement is insufficient.
If consent cannot be demonstrated, authority does not exist.

In multi-party contexts, consent is not aggregated — it is **composed**.
Each party's consent is independently verifiable
and independently revocable within the bounds of the Coalition Contract.

This distinction separates Pact from any single-agent permissions model.
A Coalition is not a group that agreed once.
It is a set of individuals whose ongoing consent is continuously legible.

---

## 5. Ephemerality by Default

Coalitions are temporary by design.

Permanent authority accumulates drift.
Drift creates opacity.
Opacity erodes trust.

Pact favors:
- Purpose-bound authority
- Time-scoped contracts
- Automatic dissolution
- Clean termination states

A coalition that has fulfilled its purpose should dissolve without residue.

---

## 6. Failure Must Be Bounded

All boundaries eventually fail.

Good boundaries fail:
- Loudly
- Locally
- Reversibly

Bad boundaries fail:
- Silently
- Systemically
- Permanently

Every feature added to Pact must answer two questions:

1. What boundary does this strengthen?
2. When this boundary fails, does it fail gracefully?

If failure is catastrophic, the design is incorrect.

---

## 7. What Pact Does Not Claim

Pact makes no claims about human character.
It makes precise claims about structure.

Pact does not guarantee:
- That humans will behave ethically
- That outcomes will be fair
- That agreements are legally enforceable in all jurisdictions
- That economic loss is impossible

Pact guarantees only:
- That authority is explicit
- That actions are attributable
- That receipts are verifiable
- That boundaries are inspectable

Trust in Pact is trust in structure, not in people.

---

## 8. Neutrality of the Protocol

The Pact specification must remain:
- Open
- Unencumbered
- Implementation-agnostic
- Governed transparently

The protocol may not be owned.
It may only be implemented.

Capture of the specification undermines legitimacy.
The moment the spec serves any single implementation over the commons,
it ceases to be a protocol and becomes a product.

---

## 9. Recognition Over Delight

Pact does not aim to amaze.

It aims to feel obvious.

The success condition is recognition:

> *"Yes. That is exactly what we agreed to."*
> *"Yes. That is exactly what happened."*

If users feel magic but not clarity,
the protocol has failed.

Delight is a byproduct of correctness.
It is never the goal.

---

## 10. The Hypothesis

Pact operates under the following hypothesis:

> Human coordination fails not because people are untrustworthy,
> but because the tools for establishing shared boundaries
> have been too expensive, too slow, or too opaque.

If this hypothesis is correct, Pact becomes infrastructure.

If it is incorrect, Pact remains a well-specified experiment —
one whose failure will be as legible as its receipts.

Protocols that cannot be falsified cannot be trusted.
Pact can be proven wrong. That is a strength, not a vulnerability.

---

## 11. The Design Test

Every feature, schema, or implementation decision must pass both:

**Boundary test:**
> What boundary does this strengthen?
> If it weakens a boundary — even in service of better UX — it damages the protocol.

**Failure test:**
> When this boundary fails, does it fail gracefully?
> Loudly, locally, reversibly — or silently, systemically, permanently?

These are not guidelines.
They are the protocol's immune system.

---

## Closing

Pact is not a productivity tool.
It is not an AI product.
It is not a startup.

It is a protocol for bounded collective agency —
the institutional primitive the internet was always missing.

All implementations must remain faithful to this philosophy.
Deviation is not forbidden. It is simply no longer Pact.

---

*This document is the constitution.
Every technical decision is measured against it.
If the spec and this document conflict, this document wins.*

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
