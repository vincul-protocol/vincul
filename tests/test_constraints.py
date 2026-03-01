"""
tests/test_constraints.py — pact.constraints test suite (unittest)

Covers the v0.2 constraint DSL: parsing, evaluation, field resolution,
subset checking, and ConstraintEvaluatorProtocol conformance.
"""

import unittest

from pact.constraints import (
    Atom, ConstraintExpression, ConstraintEvaluator,
    parse, parse_atom, parse_literal,
    evaluate, resolve_field, is_subset,
    _MISSING,
)
from pact.types import FailureCode


# ── Fixtures ──────────────────────────────────────────────────

SIMPLE_ACTION = {
    "type": "COMMIT",
    "namespace": "travel.flights",
    "resource": "flight:001",
    "params": {
        "duration_minutes": 60,
        "cost": 450.00,
        "destination": "Paris",
        "confirmed": True,
    },
}

NESTED_ACTION = {
    "type": "OBSERVE",
    "namespace": "calendar.events",
    "params": {
        "meta": {
            "priority": 5,
            "tags": "urgent",
        },
    },
}


# ═════════════════════════════════════════════════════════════
# §1: Literal Parsing
# ═════════════════════════════════════════════════════════════

class TestParseLiteral(unittest.TestCase):

    def test_integer(self):
        self.assertEqual(parse_literal("60"), 60)
        self.assertIsInstance(parse_literal("60"), int)

    def test_negative_integer(self):
        self.assertEqual(parse_literal("-10"), -10)

    def test_float(self):
        self.assertEqual(parse_literal("450.00"), 450.0)
        self.assertIsInstance(parse_literal("3.14"), float)

    def test_boolean_true(self):
        self.assertIs(parse_literal("true"), True)

    def test_boolean_false(self):
        self.assertIs(parse_literal("false"), False)

    def test_quoted_string(self):
        self.assertEqual(parse_literal('"Paris"'), "Paris")

    def test_unquoted_string(self):
        self.assertEqual(parse_literal("OBSERVE"), "OBSERVE")


# ═════════════════════════════════════════════════════════════
# §2: Atom Parsing
# ═════════════════════════════════════════════════════════════

class TestParseAtom(unittest.TestCase):

    def test_lte_integer(self):
        a = parse_atom("action.params.duration_minutes <= 60")
        self.assertEqual(a.field_path, "action.params.duration_minutes")
        self.assertEqual(a.operator, "<=")
        self.assertEqual(a.value, 60)

    def test_gte_float(self):
        a = parse_atom("action.params.cost >= 100.50")
        self.assertEqual(a.operator, ">=")
        self.assertEqual(a.value, 100.5)

    def test_eq_string(self):
        a = parse_atom('action.type == "COMMIT"')
        self.assertEqual(a.operator, "==")
        self.assertEqual(a.value, "COMMIT")

    def test_neq(self):
        a = parse_atom("action.type != OBSERVE")
        self.assertEqual(a.operator, "!=")
        self.assertEqual(a.value, "OBSERVE")

    def test_lt(self):
        a = parse_atom("action.params.cost < 500")
        self.assertEqual(a.operator, "<")
        self.assertEqual(a.value, 500)

    def test_gt(self):
        a = parse_atom("action.params.priority > 0")
        self.assertEqual(a.operator, ">")
        self.assertEqual(a.value, 0)

    def test_boolean_literal(self):
        a = parse_atom("action.params.confirmed == true")
        self.assertEqual(a.value, True)

    def test_invalid_atom_raises(self):
        with self.assertRaises(ValueError):
            parse_atom("this is not an atom")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            parse_atom("")


# ═════════════════════════════════════════════════════════════
# §3: Expression Parsing
# ═════════════════════════════════════════════════════════════

class TestParse(unittest.TestCase):

    def test_top(self):
        e = parse("TOP")
        self.assertEqual(e.kind, "TOP")
        self.assertEqual(e.atoms, ())

    def test_bottom(self):
        e = parse("BOTTOM")
        self.assertEqual(e.kind, "BOTTOM")
        self.assertEqual(e.atoms, ())

    def test_single_atom(self):
        e = parse("action.params.duration_minutes <= 60")
        self.assertEqual(e.kind, "AND")
        self.assertEqual(len(e.atoms), 1)
        self.assertEqual(e.atoms[0].field_path, "action.params.duration_minutes")

    def test_conjunction(self):
        e = parse("action.params.cost <= 500 AND action.params.duration_minutes <= 120")
        self.assertEqual(e.kind, "AND")
        self.assertEqual(len(e.atoms), 2)
        self.assertEqual(e.atoms[0].field_path, "action.params.cost")
        self.assertEqual(e.atoms[1].field_path, "action.params.duration_minutes")

    def test_three_atom_conjunction(self):
        e = parse(
            "action.type == COMMIT AND "
            "action.params.cost <= 500 AND "
            "action.params.duration_minutes <= 120"
        )
        self.assertEqual(len(e.atoms), 3)

    def test_whitespace_handling(self):
        e = parse("  TOP  ")
        self.assertEqual(e.kind, "TOP")

    def test_invalid_expression_raises(self):
        with self.assertRaises(ValueError):
            parse("NOT_A_VALID_EXPRESSION with spaces")


# ═════════════════════════════════════════════════════════════
# §4: Field Resolution
# ═════════════════════════════════════════════════════════════

class TestFieldResolution(unittest.TestCase):

    def test_top_level_field(self):
        self.assertEqual(resolve_field(SIMPLE_ACTION, "action.type"), "COMMIT")

    def test_params_field(self):
        self.assertEqual(
            resolve_field(SIMPLE_ACTION, "action.params.duration_minutes"), 60,
        )

    def test_nested_field(self):
        self.assertEqual(
            resolve_field(NESTED_ACTION, "action.params.meta.priority"), 5,
        )

    def test_missing_field_returns_sentinel(self):
        result = resolve_field(SIMPLE_ACTION, "action.params.nonexistent")
        self.assertIs(result, _MISSING)

    def test_missing_intermediate_returns_sentinel(self):
        result = resolve_field(SIMPLE_ACTION, "action.params.deep.nested.field")
        self.assertIs(result, _MISSING)

    def test_namespace_field(self):
        self.assertEqual(
            resolve_field(SIMPLE_ACTION, "action.namespace"), "travel.flights",
        )


# ═════════════════════════════════════════════════════════════
# §5: Evaluate Terminals
# ═════════════════════════════════════════════════════════════

class TestEvaluateTerminals(unittest.TestCase):

    def test_top_allows(self):
        r = evaluate("TOP", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_top_allows_empty_action(self):
        r = evaluate("TOP", {})
        self.assertTrue(r)

    def test_bottom_denies(self):
        r = evaluate("BOTTOM", SIMPLE_ACTION)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_bottom_denies_empty_action(self):
        r = evaluate("BOTTOM", {})
        self.assertFalse(r)


# ═════════════════════════════════════════════════════════════
# §6: Evaluate Atoms
# ═════════════════════════════════════════════════════════════

class TestEvaluateAtoms(unittest.TestCase):

    def test_lte_pass(self):
        r = evaluate("action.params.duration_minutes <= 60", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_lte_fail(self):
        r = evaluate("action.params.duration_minutes <= 30", SIMPLE_ACTION)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXCEEDED)

    def test_gte_pass(self):
        r = evaluate("action.params.duration_minutes >= 60", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_gte_fail(self):
        r = evaluate("action.params.duration_minutes >= 90", SIMPLE_ACTION)
        self.assertFalse(r)

    def test_lt_pass(self):
        r = evaluate("action.params.cost < 500", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_lt_boundary_fail(self):
        r = evaluate("action.params.cost < 450", SIMPLE_ACTION)
        self.assertFalse(r)

    def test_gt_pass(self):
        r = evaluate("action.params.cost > 400", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_gt_boundary_fail(self):
        r = evaluate("action.params.cost > 450", SIMPLE_ACTION)
        self.assertFalse(r)

    def test_eq_pass(self):
        r = evaluate("action.type == COMMIT", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_eq_fail(self):
        r = evaluate("action.type == OBSERVE", SIMPLE_ACTION)
        self.assertFalse(r)

    def test_neq_pass(self):
        r = evaluate("action.type != OBSERVE", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_neq_fail(self):
        r = evaluate("action.type != COMMIT", SIMPLE_ACTION)
        self.assertFalse(r)

    def test_eq_boolean(self):
        r = evaluate("action.params.confirmed == true", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_eq_string_quoted(self):
        r = evaluate('action.params.destination == "Paris"', SIMPLE_ACTION)
        self.assertTrue(r)

    def test_missing_field_denies(self):
        r = evaluate("action.params.nonexistent <= 100", SIMPLE_ACTION)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXCEEDED)


# ═════════════════════════════════════════════════════════════
# §7: Evaluate Conjunctions
# ═════════════════════════════════════════════════════════════

class TestEvaluateConjunction(unittest.TestCase):

    def test_all_atoms_pass(self):
        r = evaluate(
            "action.params.duration_minutes <= 60 AND action.params.cost <= 500",
            SIMPLE_ACTION,
        )
        self.assertTrue(r)

    def test_one_atom_fails(self):
        r = evaluate(
            "action.params.duration_minutes <= 60 AND action.params.cost <= 100",
            SIMPLE_ACTION,
        )
        self.assertFalse(r)

    def test_first_failure_wins(self):
        """First failing atom determines the error message."""
        r = evaluate(
            "action.params.cost <= 100 AND action.params.duration_minutes <= 30",
            SIMPLE_ACTION,
        )
        self.assertFalse(r)
        self.assertIn("cost", r.message)

    def test_three_atom_all_pass(self):
        r = evaluate(
            "action.type == COMMIT AND "
            "action.params.cost <= 500 AND "
            "action.params.duration_minutes <= 120",
            SIMPLE_ACTION,
        )
        self.assertTrue(r)

    def test_three_atom_last_fails(self):
        r = evaluate(
            "action.type == COMMIT AND "
            "action.params.cost <= 500 AND "
            "action.params.duration_minutes <= 30",
            SIMPLE_ACTION,
        )
        self.assertFalse(r)


# ═════════════════════════════════════════════════════════════
# §8: Subset Checking
# ═════════════════════════════════════════════════════════════

class TestSubset(unittest.TestCase):

    def test_bottom_subset_of_anything(self):
        self.assertTrue(is_subset("BOTTOM", "TOP"))
        self.assertTrue(is_subset("BOTTOM", "BOTTOM"))
        self.assertTrue(is_subset("BOTTOM", "action.params.x <= 100"))

    def test_anything_subset_of_top(self):
        self.assertTrue(is_subset("TOP", "TOP"))
        self.assertTrue(is_subset("action.params.x <= 100", "TOP"))
        self.assertTrue(is_subset(
            "action.params.x <= 50 AND action.params.y >= 10", "TOP",
        ))

    def test_top_not_subset_of_restriction(self):
        self.assertFalse(is_subset("TOP", "action.params.x <= 100"))
        self.assertFalse(is_subset("TOP", "BOTTOM"))

    def test_identical_expressions_are_subsets(self):
        expr = "action.params.x <= 100"
        self.assertTrue(is_subset(expr, expr))

    def test_tighter_upper_bound_is_subset(self):
        self.assertTrue(is_subset(
            "action.params.x <= 50",
            "action.params.x <= 100",
        ))

    def test_looser_upper_bound_not_subset(self):
        self.assertFalse(is_subset(
            "action.params.x <= 200",
            "action.params.x <= 100",
        ))

    def test_tighter_lower_bound_is_subset(self):
        self.assertTrue(is_subset(
            "action.params.x >= 100",
            "action.params.x >= 50",
        ))

    def test_looser_lower_bound_not_subset(self):
        self.assertFalse(is_subset(
            "action.params.x >= 10",
            "action.params.x >= 50",
        ))

    def test_conjunction_with_extra_atoms_is_subset(self):
        """More atoms = more restrictive = subset of fewer atoms."""
        child = "action.params.x <= 50 AND action.params.y >= 10"
        parent = "action.params.x <= 50"
        self.assertTrue(is_subset(child, parent))

    def test_conjunction_missing_required_atom_not_subset(self):
        child = "action.params.x <= 50"
        parent = "action.params.x <= 50 AND action.params.y >= 10"
        self.assertFalse(is_subset(child, parent))

    def test_equality_implies_upper_bound(self):
        """x == 5 is subset of x <= 10."""
        self.assertTrue(is_subset(
            "action.params.x == 5",
            "action.params.x <= 10",
        ))

    def test_equality_outside_bound_not_subset(self):
        """x == 15 is not subset of x <= 10."""
        self.assertFalse(is_subset(
            "action.params.x == 15",
            "action.params.x <= 10",
        ))

    def test_equality_implies_lower_bound(self):
        self.assertTrue(is_subset(
            "action.params.x == 50",
            "action.params.x >= 10",
        ))

    def test_different_fields_not_implied(self):
        self.assertFalse(is_subset(
            "action.params.y <= 50",
            "action.params.x <= 100",
        ))

    def test_lt_implies_lte(self):
        """x < 50 is subset of x <= 100."""
        self.assertTrue(is_subset(
            "action.params.x < 50",
            "action.params.x <= 100",
        ))

    def test_gt_implies_gte(self):
        """x > 100 is subset of x >= 50."""
        self.assertTrue(is_subset(
            "action.params.x > 100",
            "action.params.x >= 50",
        ))


# ═════════════════════════════════════════════════════════════
# §9: ConstraintEvaluator Protocol
# ═════════════════════════════════════════════════════════════

class TestConstraintEvaluator(unittest.TestCase):

    def test_protocol_conformance(self):
        from pact.interfaces import ConstraintEvaluatorProtocol
        evaluator = ConstraintEvaluator()
        self.assertIsInstance(evaluator, ConstraintEvaluatorProtocol)

    def test_evaluate_method(self):
        evaluator = ConstraintEvaluator()
        r = evaluator.evaluate("TOP", SIMPLE_ACTION)
        self.assertTrue(r)

    def test_evaluate_deny(self):
        evaluator = ConstraintEvaluator()
        r = evaluator.evaluate("action.params.cost <= 100", SIMPLE_ACTION)
        self.assertFalse(r)
        self.assertEqual(r.failure_code, FailureCode.SCOPE_EXCEEDED)


# ═════════════════════════════════════════════════════════════
# §10: Hash Integration
# ═════════════════════════════════════════════════════════════

class TestHashIntegration(unittest.TestCase):
    """Verify constraint hashing works with the same strings we parse."""

    def test_top_hash_matches_vector(self):
        from pact.hashing import pact_hash_constraint
        self.assertEqual(
            pact_hash_constraint("TOP"),
            "98047c362cd87227ccb70ff1635ba9fb68de6f3af390b5cf7b866af2ede53f44",
        )

    def test_atom_hash_matches_vector(self):
        from pact.hashing import pact_hash_constraint
        self.assertEqual(
            pact_hash_constraint("action.params.duration_minutes <= 60"),
            "dd07ce67ec196e23cf6a5ba26ba54a7aab1b4dd484fe96d656bd774245a4563a",
        )

    def test_parsed_and_raw_same_expression(self):
        """Parsing then serializing should yield the same canonical form."""
        expr_str = "action.params.duration_minutes <= 60"
        expr = parse(expr_str)
        self.assertEqual(expr.atoms[0].field_path, "action.params.duration_minutes")
        self.assertEqual(expr.atoms[0].operator, "<=")
        self.assertEqual(expr.atoms[0].value, 60)


if __name__ == "__main__":
    unittest.main()
