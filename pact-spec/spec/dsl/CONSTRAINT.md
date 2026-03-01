# Pact Protocol — Constraint DSL
`spec/dsl/CONSTRAINT.md` · Draft v0.1

---

## Purpose

The Pact Constraint DSL defines the language used to express `predicate` and `ceiling` fields in a Scope. It has exactly one job:

**Express what is permitted within a domain boundary.**

The DSL is intentionally boring. It is not a programming language. It has no variables, no functions, no side effects, and no dynamic evaluation. Every valid expression has a decidable truth value given a proposed action. Every pair of expressions has a decidable intersection.

This document defines: the grammar, allowed operators, normal form, intersection algorithm, and subset proof rules.

---

## 1. Design Constraints (Non-Negotiable)

The DSL must be:

| Property | Requirement |
|---|---|
| **Closed under intersection** | `intersect(A, B)` always produces a valid ConstraintExpression |
| **Decidable** | Given an action and an expression, evaluation always terminates |
| **Serializable** | Every expression has a canonical text form; two semantically identical expressions produce identical canonical forms |
| **Not Turing-complete** | No recursion, no loops, no dynamic dispatch |
| **Subset-provable** | Given two expressions A and B, it is decidable whether `A ⊆ B` |
| **Implementation-agnostic** | The DSL does not reference any namespace, vendor, or runtime |

The DSL must **not** express:

- Lifecycle rules (status, revocation, expiry — those live in the schema)
- Type escalation logic (that lives in the type lattice)
- Delegation logic (that lives in the schema invariants)
- Turing-complete computation of any kind

---

## 2. Core Concepts

### 2.1 Action

An **action** is the unit the DSL reasons about. Formally:

```
Action = {
  type:      OperationType,          # OBSERVE | PROPOSE | COMMIT
  namespace: hierarchical_path,      # e.g. "calendar.events"
  resource:  resource_identifier,    # e.g. "event:abc123"
  params:    map<string, scalar>     # e.g. { duration_minutes: 60 }
}
```

A ConstraintExpression is evaluated against an Action. The result is always `permitted` or `denied`.

### 2.2 Scalar types

DSL values are one of:

| Type | Description | Example |
|---|---|---|
| `integer` | Signed 64-bit integer | `60`, `-1` |
| `decimal` | Fixed-point decimal (precision defined in serialization spec) | `9.99` |
| `string` | UTF-8 string, no interpolation | `"confirmed"` |
| `boolean` | `true` or `false` | `true` |
| `duration` | ISO 8601 duration | `PT1H` |
| `enum` | Named value from a closed set declared in the expression | `status::confirmed` |

No dynamic types. No null. No lists as values (use `in` operator instead).

---

## 3. Grammar

```
ConstraintExpression ::=
    TOP                                          # permits everything (ceiling default)
  | BOTTOM                                       # permits nothing
  | Atom
  | NOT Atom                                     # negation of a single atom only
  | ConstraintExpression AND ConstraintExpression
  | ConstraintExpression OR ConstraintExpression
  | "(" ConstraintExpression ")"

Atom ::=
    FieldRef Comparator ScalarLiteral
  | FieldRef "in" "[" ScalarLiteral ("," ScalarLiteral)* "]"
  | FieldRef "not_in" "[" ScalarLiteral ("," ScalarLiteral)* "]"

FieldRef ::=
    "action.type"
  | "action.namespace"
  | "action.resource"
  | "action.params." Identifier

Comparator ::=
    "==" | "!=" | "<" | "<=" | ">" | ">="

ScalarLiteral ::=
    IntegerLiteral
  | DecimalLiteral
  | StringLiteral
  | BooleanLiteral
  | DurationLiteral
  | EnumLiteral

Identifier ::= [a-z][a-z0-9_]*
```

### 3.1 Restrictions

- `NOT` may only wrap a single `Atom`, not a compound expression. `NOT (A AND B)` is not valid syntax. Use `(NOT A) OR (NOT B)` only if both are atoms.
- Nesting depth is bounded at **8 levels**. Expressions exceeding this depth are malformed.
- A single expression may contain at most **64 atoms**. Expressions exceeding this are malformed.
- `OR` is permitted but implementations should treat high-OR-count expressions as a complexity signal. The normal form (§4) converts OR to disjunctive normal form, which bounds reasoning cost.

### 3.2 Special terminals

- **`TOP`** — the universal constraint. Permits any action within the domain. Used as the default `ceiling` when none is specified. `intersect(TOP, X) = X` for any X.
- **`BOTTOM`** — the empty constraint. Permits nothing. `intersect(BOTTOM, X) = BOTTOM` for any X. A scope with `predicate = BOTTOM` is valid but useless; implementations may warn.

---

## 4. Normal Form

To enable canonical serialization and decidable subset proofs, every ConstraintExpression must be reducible to **Disjunctive Normal Form (DNF)**:

```
DNF ::= Clause (OR Clause)*
Clause ::= Literal (AND Literal)*
Literal ::= Atom | NOT Atom
```

### 4.1 Normalization rules

1. Eliminate double negation: `NOT NOT A → A`
2. Apply De Morgan's (only for `NOT` over compound — which is disallowed in syntax, so this is only needed during import/migration from external formats)
3. Distribute AND over OR: `A AND (B OR C) → (A AND B) OR (A AND C)`
4. Sort atoms within each clause lexicographically by FieldRef, then literal
5. Sort clauses lexicographically
6. Deduplicate identical clauses
7. Eliminate contradictory clauses (a clause containing both `A` and `NOT A` reduces to `BOTTOM` and is removed)
8. If all clauses are eliminated: expression = `BOTTOM`
9. If any clause is empty (no literals): expression = `TOP`

The canonical serialization is the normalized DNF expression in the grammar above.

---

## 5. Intersection Algorithm

`intersect(A, B)` produces the ConstraintExpression that permits exactly what both A and B permit.

```
intersect(TOP, B)    = B
intersect(A, TOP)    = A
intersect(BOTTOM, B) = BOTTOM
intersect(A, BOTTOM) = BOTTOM

intersect(DNF_A, DNF_B):
  result_clauses = []
  for each clause_a in DNF_A.clauses:
    for each clause_b in DNF_B.clauses:
      merged = clause_a.literals ∪ clause_b.literals
      if not contradictory(merged):
        result_clauses.append(merged)
  if result_clauses is empty: return BOTTOM
  return normalize(OR(result_clauses))
```

Where `contradictory(literals)` returns true if the set contains both `Atom` and `NOT Atom` for any Atom.

**Complexity:** O(|A| × |B|) clauses before deduplication, where |A| and |B| are clause counts. Given the 64-atom bound, this is bounded in practice.

**Closure guarantee:** The result is always a valid ConstraintExpression. Intersection never produces an expression outside the grammar.

---

## 6. Subset Proof Rules

`A ⊆ B` means "every action permitted by A is also permitted by B."

This must be decidable for two purposes:
1. Schema validation: `predicate ⊆ ceiling`
2. Delegation validation: `child.ceiling ⊆ parent.ceiling`

### 6.1 Algorithm

```
A ⊆ B iff intersect(A, NOT_B) = BOTTOM
```

Where `NOT_B` is the complement of B. Since full complement of a DNF expression is a CNF expression (which may be complex), we use the following equivalent and more tractable check:

```
A ⊆ B iff for every clause C in normalize(A):
  there exists a clause D in normalize(B) such that
  every literal in D is also in C
```

In plain language: every way A permits an action must be covered by at least one clause in B.

### 6.2 Special cases

| Case | Result |
|---|---|
| `BOTTOM ⊆ X` | Always true (nothing is permitted, so nothing violates X) |
| `X ⊆ TOP` | Always true |
| `TOP ⊆ BOTTOM` | False (unless X is BOTTOM) |
| `A ⊆ A` | Always true |

---

## 7. Budget and Threshold Constraints

Budgets are a special constraint class that governs cumulative or bounded resource consumption — e.g., "total spend under $500" or "at most 3 commits per hour."

These are not expressible as pure stateless predicates. They require state.

### 7.1 Budget atoms

Budget constraints are declared as a distinct atom class:

```
BudgetAtom ::=
    "budget." Identifier Comparator ScalarLiteral

Examples:
  budget.total_spend <= 500.00
  budget.commits_per_hour <= 3
  budget.duration_minutes <= 120
```

Budget atoms are evaluated against a runtime budget ledger, not against action fields alone. Implementations must maintain per-scope budget ledgers and decrement them at commit time.

### 7.2 Budget semantics

- Budget atoms in `ceiling` are **hard limits** — exceeding them is a violation regardless of predicate
- Budget atoms in `predicate` are **authorization gates** — an action is denied if it would exceed the predicate budget
- At delegation, child budget ceiling ≤ parent budget ceiling (same containment rule as all other ceiling fields)
- Budget state is not transferred between scopes; each scope tracks its own ledger
- Revocation zeroes the scope's future authorization but does not reverse past consumption

### 7.3 Budget is not accounting

The DSL expresses budget constraints. It does not perform settlement, reconciliation, or billing. Those are implementation-layer concerns.

---

## 8. What the DSL Explicitly Excludes

The following are not part of the DSL and must not be added:

| Excluded | Reason |
|---|---|
| Time/date conditions (e.g., `action.time < "2025-01-01"`) | Lifecycle is handled by `expires_at` in the schema |
| Principal identity conditions (e.g., `action.caller == "user:123"`) | Identity binding is handled at the contract layer |
| Namespace wildcard matching | Containment uses structural prefix only (see SCHEMA.md §2.2) |
| Conditional delegation | Delegation is binary; conditions live in the schema |
| Cross-field arithmetic | e.g., `action.params.end - action.params.start <= 60` — excluded in v0.1; may be revisited |
| External function calls | No runtime lookup of any kind |
| Recursive expressions | Grammar is explicitly non-recursive beyond bounded nesting |

If an implementation requires any of the above, it must handle them outside the Pact constraint layer. The DSL does not grow to accommodate implementation needs.

---

## 9. Serialization

The canonical serialization of a ConstraintExpression is its normalized DNF form in the grammar defined in §3, encoded as UTF-8, with the following formatting rules:

- Keywords (`AND`, `OR`, `NOT`, `TOP`, `BOTTOM`, `in`, `not_in`) are uppercase/lowercase as shown
- Atoms are serialized with single spaces around operators
- Clauses within DNF are separated by ` OR `
- Literals within a clause are separated by ` AND `
- Parentheses are added only where required by grammar (around OR clauses combined with AND at higher level)
- String literals are double-quoted with backslash escaping
- Decimal literals use `.` as decimal separator, no thousands separator
- Duration literals use ISO 8601 format

Two expressions that are semantically equivalent (same permitted action set) **must** produce the same canonical serialization after normalization.

The `descriptor_hash` in the Scope schema is computed over canonical serializations of `predicate` and `ceiling`.

Precise byte-level serialization rules are defined in `spec/serialization/CANONICAL.md` (not yet written).

---

## 10. Locked Invariants

| # | Invariant |
|---|---|
| 1 | Every ConstraintExpression has a decidable evaluation result given an Action |
| 2 | `intersect(A, B)` always produces a valid ConstraintExpression |
| 3 | `A ⊆ B` is decidable for any two ConstraintExpressions |
| 4 | Normalization is deterministic and produces identical output for semantically identical expressions |
| 5 | `NOT` may only negate a single Atom |
| 6 | Nesting depth ≤ 8; atom count ≤ 64 |
| 7 | Budget atoms in `ceiling` are hard limits; never overridable by predicate |
| 8 | The DSL contains no Turing-complete constructs |
| 9 | No external state is consulted during evaluation (except budget ledger for BudgetAtoms) |
| 10 | The DSL does not expand. Implementation needs do not modify the grammar. |

---
`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`

Generated on 2026-03-01  @smazor project
