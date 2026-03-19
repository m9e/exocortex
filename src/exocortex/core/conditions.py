"""Declarative condition evaluation for graph edge traversal.

Evaluates ConditionSpec objects against graph state dictionaries.
All comparisons are declarative — no eval(), exec(), or dynamic code execution.
"""

from __future__ import annotations

from typing import Any

from exocortex.core.graph import ConditionOp, ConditionSpec


def _resolve_field(state: dict[str, Any], field: str) -> tuple[bool, Any]:
    """Resolve a possibly dot-notated field path against a state dict.

    Returns:
        A tuple of (field_exists, field_value). When field_exists is False,
        field_value is None.
    """
    parts = field.split(".")
    current: Any = state

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None

    return True, current


def evaluate_condition(condition: ConditionSpec, state: dict[str, Any]) -> bool:
    """Evaluate a declarative condition against graph state.

    Args:
        condition: The condition specification to evaluate.
        state: The current graph state dictionary.

    Returns:
        True if the condition is satisfied, False otherwise.
        Returns False if the referenced field does not exist,
        unless the operator is EXISTS.
    """
    exists, field_value = _resolve_field(state, condition.field)
    op = condition.operator

    # EXISTS is the only operator that doesn't require the field to be present.
    if op is ConditionOp.EXISTS:
        return exists

    # All other operators require the field to exist.
    if not exists:
        return False

    compare_value = condition.value

    if op is ConditionOp.EQ:
        return field_value == compare_value

    if op is ConditionOp.NEQ:
        return field_value != compare_value

    if op is ConditionOp.IS_TRUE:
        return bool(field_value) is True

    if op is ConditionOp.IS_FALSE:
        return bool(field_value) is False

    if op is ConditionOp.IN:
        try:
            return field_value in compare_value
        except TypeError:
            return False

    if op is ConditionOp.NOT_IN:
        try:
            return field_value not in compare_value
        except TypeError:
            return False

    # Ordered comparisons: gt, gte, lt, lte
    # Return False on incompatible types rather than raising.
    if op is ConditionOp.GT:
        try:
            return field_value > compare_value
        except TypeError:
            return False

    if op is ConditionOp.GTE:
        try:
            return field_value >= compare_value
        except TypeError:
            return False

    if op is ConditionOp.LT:
        try:
            return field_value < compare_value
        except TypeError:
            return False

    if op is ConditionOp.LTE:
        try:
            return field_value <= compare_value
        except TypeError:
            return False

    # Should be unreachable if ConditionOp enum is exhaustive.
    msg = f"Unknown operator: {op}"
    raise ValueError(msg)
