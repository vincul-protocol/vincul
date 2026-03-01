"""
pact.constraints — Constraint DSL parser, evaluator, and subset checker
spec: spec/dsl/CONSTRAINT.md

v0.2 grammar (conjunction-only):
    Expression := TOP | BOTTOM | Atom | And(Atom, Atom, ...)
    Atom       := field_path operator literal
    operator   := <= | >= | < | > | == | !=
    literal    := number | string | boolean
    field_path := dotted path resolved against an action dict

No OR, no NOT, no nesting beyond conjunction.

Depends on: pact.types
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pact.types import FailureCode, ValidationResult


# ── Data structures ──────────────────────────────────────────

OPERATORS = frozenset({"<=", ">=", "<", ">", "==", "!="})

# Regex: field_path <operator> literal
# Captures: (field_path) (operator) (literal_rest)
_ATOM_RE = re.compile(
    r"^([\w.]+)\s+(<=|>=|<|>|==|!=)\s+(.+)$"
)


@dataclass(frozen=True)
class Atom:
    """A single constraint atom: field_path op value."""
    field_path: str
    operator: str
    value: int | float | str | bool


@dataclass(frozen=True)
class ConstraintExpression:
    """
    A parsed constraint expression.
    kind: "TOP", "BOTTOM", or "AND"
    atoms: empty for TOP/BOTTOM, 1+ for AND
    """
    kind: str
    atoms: tuple[Atom, ...]


# ── Parsing ──────────────────────────────────────────────────

def parse_literal(raw: str) -> int | float | str | bool:
    """Parse a literal value from its string representation."""
    stripped = raw.strip()

    # Boolean
    if stripped == "true":
        return True
    if stripped == "false":
        return False

    # Quoted string
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped[1:-1]

    # Integer
    try:
        return int(stripped)
    except ValueError:
        pass

    # Float
    try:
        return float(stripped)
    except ValueError:
        pass

    # Unquoted string (e.g. OBSERVE, COMMIT)
    return stripped


def parse_atom(atom_str: str) -> Atom:
    """
    Parse a single atom string into an Atom.
    e.g. "action.params.duration_minutes <= 60"
    """
    m = _ATOM_RE.match(atom_str.strip())
    if not m:
        raise ValueError(f"Invalid constraint atom: {atom_str!r}")

    field_path = m.group(1)
    operator = m.group(2)
    value = parse_literal(m.group(3))

    return Atom(field_path=field_path, operator=operator, value=value)


def parse(expression: str) -> ConstraintExpression:
    """
    Parse a constraint expression string.

    Supports: TOP, BOTTOM, single atom, atoms joined by ' AND '.
    Raises ValueError on unparseable input.
    """
    expr = expression.strip()

    if expr == "TOP":
        return ConstraintExpression(kind="TOP", atoms=())
    if expr == "BOTTOM":
        return ConstraintExpression(kind="BOTTOM", atoms=())

    # Split on ' AND ' (case-sensitive)
    parts = expr.split(" AND ")
    atoms = tuple(parse_atom(part) for part in parts)

    return ConstraintExpression(kind="AND", atoms=atoms)


# ── Field resolution ─────────────────────────────────────────

_MISSING = object()


def resolve_field(action: dict[str, Any], field_path: str) -> Any:
    """
    Resolve a dotted field path against an action dict.

    "action.params.duration_minutes" → action["params"]["duration_minutes"]

    The leading "action." prefix is stripped since the dict root IS the action.
    Returns _MISSING sentinel if the path doesn't resolve.
    """
    # Strip leading "action." if present
    path = field_path
    if path.startswith("action."):
        path = path[len("action."):]

    current: Any = action
    for key in path.split("."):
        if not isinstance(current, dict):
            return _MISSING
        current = current.get(key, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


# ── Atom evaluation ──────────────────────────────────────────

def _compare(actual: Any, operator: str, expected: Any) -> bool:
    """Apply a comparison operator. Returns False on type mismatch."""
    try:
        if operator == "==":
            return actual == expected
        if operator == "!=":
            return actual != expected
        if operator == "<=":
            return actual <= expected
        if operator == ">=":
            return actual >= expected
        if operator == "<":
            return actual < expected
        if operator == ">":
            return actual > expected
    except TypeError:
        return False
    return False


def _evaluate_atom(atom: Atom, action: dict[str, Any]) -> ValidationResult:
    """Evaluate a single atom against an action dict."""
    actual = resolve_field(action, atom.field_path)
    if actual is _MISSING:
        return ValidationResult.deny(
            FailureCode.SCOPE_EXCEEDED,
            f"Field {atom.field_path!r} not found in action; "
            f"failing closed.",
            field_path=atom.field_path,
        )

    if _compare(actual, atom.operator, atom.value):
        return ValidationResult.allow()

    return ValidationResult.deny(
        FailureCode.SCOPE_EXCEEDED,
        f"Constraint violated: {atom.field_path} {atom.operator} {atom.value} "
        f"(actual: {actual!r})",
        field_path=atom.field_path,
        operator=atom.operator,
        expected=atom.value,
        actual=actual,
    )


# ── Expression evaluation ────────────────────────────────────

def evaluate(expression: str, action: dict[str, Any]) -> ValidationResult:
    """
    Evaluate a constraint expression against an action dict.

    Returns ValidationResult.allow() or ValidationResult.deny(SCOPE_EXCEEDED, ...).
    First failing atom wins — evaluation stops at the first violation.
    """
    expr = parse(expression)

    if expr.kind == "TOP":
        return ValidationResult.allow()
    if expr.kind == "BOTTOM":
        return ValidationResult.deny(
            FailureCode.SCOPE_EXCEEDED,
            "Constraint is BOTTOM; nothing is permitted.",
        )

    # AND: all atoms must pass
    for atom in expr.atoms:
        result = _evaluate_atom(atom, action)
        if not result:
            return result

    return ValidationResult.allow()


# ── Subset checking ──────────────────────────────────────────

def _atom_implies(parent_atom: Atom, child_atom: Atom) -> bool:
    """
    Check if child_atom is at least as restrictive as parent_atom
    on the same field path with a compatible operator.

    For same-field, same-direction bounds:
      child x <= 50  implies parent x <= 100  (tighter upper bound)
      child x >= 100 implies parent x >= 50   (tighter lower bound)
      child x == 5   implies parent x <= 10   (equality within bound)
    """
    if parent_atom.field_path != child_atom.field_path:
        return False

    # Exact match
    if child_atom == parent_atom:
        return True

    pv = parent_atom.value
    cv = child_atom.value
    pop = parent_atom.operator
    cop = child_atom.operator

    try:
        # Child == implies parent <=, >=, <, > if value satisfies
        if cop == "==":
            return _compare(cv, pop, pv)

        # Same operator, tighter bound
        if pop == cop:
            if pop in ("<=", "<"):
                return cv <= pv  # child tighter upper bound
            if pop in (">=", ">"):
                return cv >= pv  # child tighter lower bound

        # <= vs <: child x <= 50 implies parent x < 100 if 50 < 100
        if pop == "<" and cop == "<=":
            return cv < pv
        if pop == "<=" and cop == "<":
            return cv <= pv

        # >= vs >: child x >= 100 implies parent x > 50 if 100 > 50
        if pop == ">" and cop == ">=":
            return cv > pv
        if pop == ">=" and cop == ">":
            return cv >= pv

    except TypeError:
        return False

    return False


def is_subset(child_expr: str, parent_expr: str) -> bool:
    """
    Check if child_expr ⊆ parent_expr.

    "Every action permitted by child is also permitted by parent."

    For v0.2 conjunction-only grammar:
      BOTTOM ⊆ anything         → True
      anything ⊆ TOP            → True
      TOP ⊆ non-TOP             → False
      And(A) ⊆ And(B)           → every atom in B is implied by some atom in A
    """
    child = parse(child_expr)
    parent = parse(parent_expr)

    # BOTTOM permits nothing — subset of anything
    if child.kind == "BOTTOM":
        return True

    # Everything is subset of TOP
    if parent.kind == "TOP":
        return True

    # TOP is not subset of any restriction
    if child.kind == "TOP":
        return False

    # BOTTOM parent: only BOTTOM child is subset (handled above)
    if parent.kind == "BOTTOM":
        return False

    # Both are AND: every parent atom must be implied by some child atom
    for parent_atom in parent.atoms:
        if not any(_atom_implies(parent_atom, child_atom) for child_atom in child.atoms):
            return False

    return True


# ── ConstraintEvaluator (satisfies ConstraintEvaluatorProtocol) ──

class ConstraintEvaluator:
    """
    Thin wrapper satisfying ConstraintEvaluatorProtocol.
    The module-level functions (evaluate, parse, is_subset) are
    usable standalone without instantiation.
    """

    def evaluate(self, expression: str, action: dict[str, Any]) -> ValidationResult:
        return evaluate(expression, action)
