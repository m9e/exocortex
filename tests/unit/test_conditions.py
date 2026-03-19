"""Comprehensive tests for declarative condition evaluation."""

from __future__ import annotations

from exocortex.core.conditions import evaluate_condition
from exocortex.core.graph import ConditionOp, ConditionSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cond(field: str, op: ConditionOp, value: object = None) -> ConditionSpec:
    """Shorthand for building a ConditionSpec."""
    return ConditionSpec(field=field, operator=op, value=value)


# ---------------------------------------------------------------------------
# EQ / NEQ
# ---------------------------------------------------------------------------


class TestEq:
    def test_equal_strings(self) -> None:
        assert evaluate_condition(_cond("status", ConditionOp.EQ, "done"), {"status": "done"})

    def test_not_equal_strings(self) -> None:
        cond = _cond("status", ConditionOp.EQ, "done")
        assert not evaluate_condition(cond, {"status": "pending"})

    def test_equal_int(self) -> None:
        assert evaluate_condition(_cond("count", ConditionOp.EQ, 5), {"count": 5})

    def test_equal_none(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, None), {"val": None})

    def test_equal_bool(self) -> None:
        assert evaluate_condition(_cond("flag", ConditionOp.EQ, True), {"flag": True})


class TestNeq:
    def test_different_values(self) -> None:
        assert evaluate_condition(_cond("status", ConditionOp.NEQ, "done"), {"status": "pending"})

    def test_same_values(self) -> None:
        assert not evaluate_condition(_cond("status", ConditionOp.NEQ, "done"), {"status": "done"})

    def test_neq_none(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.NEQ, None), {"val": 0})


# ---------------------------------------------------------------------------
# GT / GTE / LT / LTE
# ---------------------------------------------------------------------------


class TestGt:
    def test_greater(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.GT, 80), {"score": 90})

    def test_equal_not_greater(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.GT, 80), {"score": 80})

    def test_less_not_greater(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.GT, 80), {"score": 70})

    def test_float_comparison(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.GT, 0.5), {"score": 0.9})


class TestGte:
    def test_greater(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.GTE, 80), {"score": 90})

    def test_equal(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.GTE, 80), {"score": 80})

    def test_less(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.GTE, 80), {"score": 70})


class TestLt:
    def test_less(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.LT, 80), {"score": 70})

    def test_equal_not_less(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.LT, 80), {"score": 80})

    def test_greater_not_less(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.LT, 80), {"score": 90})


class TestLte:
    def test_less(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.LTE, 80), {"score": 70})

    def test_equal(self) -> None:
        assert evaluate_condition(_cond("score", ConditionOp.LTE, 80), {"score": 80})

    def test_greater(self) -> None:
        assert not evaluate_condition(_cond("score", ConditionOp.LTE, 80), {"score": 90})


# ---------------------------------------------------------------------------
# IN / NOT_IN
# ---------------------------------------------------------------------------


class TestIn:
    def test_value_in_list(self) -> None:
        assert evaluate_condition(
            _cond("status", ConditionOp.IN, ["done", "cancelled"]),
            {"status": "done"},
        )

    def test_value_not_in_list(self) -> None:
        assert not evaluate_condition(
            _cond("status", ConditionOp.IN, ["done", "cancelled"]),
            {"status": "pending"},
        )

    def test_value_in_set(self) -> None:
        assert evaluate_condition(
            _cond("status", ConditionOp.IN, {"done", "cancelled"}),
            {"status": "done"},
        )

    def test_value_in_empty_list(self) -> None:
        assert not evaluate_condition(
            _cond("status", ConditionOp.IN, []),
            {"status": "done"},
        )


class TestNotIn:
    def test_value_not_in_list(self) -> None:
        assert evaluate_condition(
            _cond("status", ConditionOp.NOT_IN, ["done", "cancelled"]),
            {"status": "pending"},
        )

    def test_value_in_list(self) -> None:
        assert not evaluate_condition(
            _cond("status", ConditionOp.NOT_IN, ["done", "cancelled"]),
            {"status": "done"},
        )

    def test_value_not_in_empty_list(self) -> None:
        assert evaluate_condition(
            _cond("status", ConditionOp.NOT_IN, []),
            {"status": "done"},
        )


# ---------------------------------------------------------------------------
# IS_TRUE / IS_FALSE
# ---------------------------------------------------------------------------


class TestIsTrue:
    def test_true(self) -> None:
        assert evaluate_condition(_cond("flag", ConditionOp.IS_TRUE), {"flag": True})

    def test_false(self) -> None:
        assert not evaluate_condition(_cond("flag", ConditionOp.IS_TRUE), {"flag": False})

    def test_truthy_int(self) -> None:
        assert evaluate_condition(_cond("count", ConditionOp.IS_TRUE), {"count": 1})

    def test_falsy_int(self) -> None:
        assert not evaluate_condition(_cond("count", ConditionOp.IS_TRUE), {"count": 0})

    def test_truthy_string(self) -> None:
        assert evaluate_condition(_cond("name", ConditionOp.IS_TRUE), {"name": "hello"})

    def test_falsy_empty_string(self) -> None:
        assert not evaluate_condition(_cond("name", ConditionOp.IS_TRUE), {"name": ""})

    def test_truthy_nonempty_list(self) -> None:
        assert evaluate_condition(_cond("items", ConditionOp.IS_TRUE), {"items": [1]})

    def test_falsy_empty_list(self) -> None:
        assert not evaluate_condition(_cond("items", ConditionOp.IS_TRUE), {"items": []})

    def test_falsy_none(self) -> None:
        assert not evaluate_condition(_cond("val", ConditionOp.IS_TRUE), {"val": None})


class TestIsFalse:
    def test_false(self) -> None:
        assert evaluate_condition(_cond("flag", ConditionOp.IS_FALSE), {"flag": False})

    def test_true(self) -> None:
        assert not evaluate_condition(_cond("flag", ConditionOp.IS_FALSE), {"flag": True})

    def test_falsy_zero(self) -> None:
        assert evaluate_condition(_cond("count", ConditionOp.IS_FALSE), {"count": 0})

    def test_falsy_none(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.IS_FALSE), {"val": None})

    def test_falsy_empty_string(self) -> None:
        assert evaluate_condition(_cond("name", ConditionOp.IS_FALSE), {"name": ""})

    def test_falsy_empty_list(self) -> None:
        assert evaluate_condition(_cond("items", ConditionOp.IS_FALSE), {"items": []})


# ---------------------------------------------------------------------------
# EXISTS
# ---------------------------------------------------------------------------


class TestExists:
    def test_field_exists(self) -> None:
        assert evaluate_condition(_cond("key", ConditionOp.EXISTS), {"key": "value"})

    def test_field_missing(self) -> None:
        assert not evaluate_condition(_cond("key", ConditionOp.EXISTS), {"other": "value"})

    def test_field_exists_with_none_value(self) -> None:
        assert evaluate_condition(_cond("key", ConditionOp.EXISTS), {"key": None})

    def test_field_exists_with_false_value(self) -> None:
        assert evaluate_condition(_cond("key", ConditionOp.EXISTS), {"key": False})

    def test_field_exists_with_zero(self) -> None:
        assert evaluate_condition(_cond("key", ConditionOp.EXISTS), {"key": 0})

    def test_field_exists_empty_string(self) -> None:
        assert evaluate_condition(_cond("key", ConditionOp.EXISTS), {"key": ""})

    def test_empty_state(self) -> None:
        assert not evaluate_condition(_cond("key", ConditionOp.EXISTS), {})


# ---------------------------------------------------------------------------
# Nested field access (dot notation)
# ---------------------------------------------------------------------------


class TestNestedFieldAccess:
    def test_one_level_deep(self) -> None:
        state = {"result": {"score": 95}}
        assert evaluate_condition(_cond("result.score", ConditionOp.GT, 90), state)

    def test_two_levels_deep(self) -> None:
        state = {"a": {"b": {"c": 42}}}
        assert evaluate_condition(_cond("a.b.c", ConditionOp.EQ, 42), state)

    def test_nested_field_missing_intermediate(self) -> None:
        state = {"a": {"x": 1}}
        assert not evaluate_condition(_cond("a.b.c", ConditionOp.EQ, 42), state)

    def test_nested_field_missing_root(self) -> None:
        state = {"x": 1}
        assert not evaluate_condition(_cond("a.b.c", ConditionOp.EQ, 42), state)

    def test_nested_exists_present(self) -> None:
        state = {"result": {"status": "ok"}}
        assert evaluate_condition(_cond("result.status", ConditionOp.EXISTS), state)

    def test_nested_exists_missing(self) -> None:
        state = {"result": {"other": "ok"}}
        assert not evaluate_condition(_cond("result.status", ConditionOp.EXISTS), state)

    def test_nested_in_operator(self) -> None:
        state = {"result": {"status": "done"}}
        assert evaluate_condition(
            _cond("result.status", ConditionOp.IN, ["done", "cancelled"]),
            state,
        )

    def test_nested_is_true(self) -> None:
        state = {"config": {"enabled": True}}
        assert evaluate_condition(_cond("config.enabled", ConditionOp.IS_TRUE), state)


# ---------------------------------------------------------------------------
# Missing fields (non-EXISTS operators)
# ---------------------------------------------------------------------------


class TestMissingFields:
    def test_eq_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.EQ, "value"), {})

    def test_neq_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.NEQ, "value"), {})

    def test_gt_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.GT, 5), {})

    def test_gte_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.GTE, 5), {})

    def test_lt_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.LT, 5), {})

    def test_lte_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.LTE, 5), {})

    def test_in_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.IN, [1, 2]), {})

    def test_not_in_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.NOT_IN, [1, 2]), {})

    def test_is_true_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.IS_TRUE), {})

    def test_is_false_missing_field(self) -> None:
        assert not evaluate_condition(_cond("missing", ConditionOp.IS_FALSE), {})


# ---------------------------------------------------------------------------
# Type mismatches
# ---------------------------------------------------------------------------


class TestTypeMismatches:
    def test_gt_string_vs_int(self) -> None:
        """Comparing incompatible types returns False, not an error."""
        assert not evaluate_condition(_cond("val", ConditionOp.GT, 5), {"val": "hello"})

    def test_lt_string_vs_int(self) -> None:
        assert not evaluate_condition(_cond("val", ConditionOp.LT, 5), {"val": "hello"})

    def test_gte_none_vs_int(self) -> None:
        assert not evaluate_condition(_cond("val", ConditionOp.GTE, 5), {"val": None})

    def test_lte_none_vs_int(self) -> None:
        assert not evaluate_condition(_cond("val", ConditionOp.LTE, 5), {"val": None})

    def test_in_with_non_iterable_compare_value(self) -> None:
        """If the compare value is not iterable, IN returns False."""
        assert not evaluate_condition(_cond("val", ConditionOp.IN, 42), {"val": 42})

    def test_not_in_with_non_iterable_compare_value(self) -> None:
        assert not evaluate_condition(_cond("val", ConditionOp.NOT_IN, 42), {"val": 42})

    def test_eq_int_vs_string(self) -> None:
        """Different types are simply not equal."""
        assert not evaluate_condition(_cond("val", ConditionOp.EQ, "5"), {"val": 5})

    def test_neq_int_vs_string(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.NEQ, "5"), {"val": 5})


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_eq_none(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, None), {"val": None})

    def test_none_neq_something(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.NEQ, "x"), {"val": None})

    def test_empty_string_eq(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, ""), {"val": ""})

    def test_empty_list_eq(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, []), {"val": []})

    def test_zero_eq(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, 0), {"val": 0})

    def test_false_eq(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.EQ, False), {"val": False})

    def test_nested_into_non_dict(self) -> None:
        """Dot notation through a non-dict intermediate returns False."""
        state = {"result": "not_a_dict"}
        assert not evaluate_condition(_cond("result.score", ConditionOp.EQ, 42), state)

    def test_nested_into_list(self) -> None:
        """Dot notation through a list (not dict) returns False."""
        state = {"result": [1, 2, 3]}
        assert not evaluate_condition(_cond("result.0", ConditionOp.EQ, 1), state)

    def test_empty_field_name(self) -> None:
        """An empty string field name resolves against key '' in the dict."""
        state = {"": "empty_key"}
        assert evaluate_condition(_cond("", ConditionOp.EQ, "empty_key"), state)

    def test_field_with_dots_as_actual_keys(self) -> None:
        """Dot notation splits — if actual key contains dots, it won't match."""
        state = {"a.b": "value"}
        # "a.b" is interpreted as state["a"]["b"], not state["a.b"]
        assert not evaluate_condition(_cond("a.b", ConditionOp.EQ, "value"), state)

    def test_boolean_false_is_not_none(self) -> None:
        assert evaluate_condition(_cond("val", ConditionOp.NEQ, None), {"val": False})

    def test_exists_nested_with_none_value(self) -> None:
        """A nested field that exists but is None should return True for EXISTS."""
        state = {"result": {"score": None}}
        assert evaluate_condition(_cond("result.score", ConditionOp.EXISTS), state)
